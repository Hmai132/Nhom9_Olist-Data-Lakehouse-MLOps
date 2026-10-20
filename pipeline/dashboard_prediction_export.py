"""Export a retrospective, label-free dashboard view of both frozen ML outputs.

The classifier score is the existing one-time July-August test output. The
regression model is only scored on those same rows for display; this does not
evaluate or retune its regression performance on test labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import MODEL_FEATURES as CLASSIFIER_FEATURES
from pipeline.ml_dataset import FEATURE_COLUMNS
from pipeline.regression_baseline import MODEL_FEATURES as REGRESSION_FEATURES, file_sha256


def export(data_dir: Path, model_dir: Path) -> dict:
    manifest_path = data_dir / "manifest.json"
    test_path = data_dir / "test.parquet"
    classifier_path = model_dir / "historical_test_predictions.csv"
    classifier_metrics_path = model_dir / "historical_test_metrics.json"
    regression_path = model_dir / "regression_linear_asof.joblib"
    regression_metrics_path = model_dir / "regression_asof_metrics.json"
    policy_path = model_dir / "hybrid_policy_test_exploratory_decisions.csv"
    policy_metrics_path = model_dir / "hybrid_policy_test_exploratory_metrics.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    classifier_metrics = json.loads(classifier_metrics_path.read_text(encoding="utf-8"))
    regression_metrics = json.loads(regression_metrics_path.read_text(encoding="utf-8"))
    policy_metrics = json.loads(policy_metrics_path.read_text(encoding="utf-8"))
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("Prepared feature contract differs from the model code")
    if set(REGRESSION_FEATURES) != set(CLASSIFIER_FEATURES):
        raise ValueError("The two models do not share the same input feature contract")
    if classifier_metrics["input_sha256"]["test_parquet"] != file_sha256(test_path):
        raise ValueError("Frozen classifier test input changed")
    if classifier_metrics["test_rows"] != manifest["splits"]["test"]["rows"]:
        raise ValueError("Frozen classifier test row count changed")
    if regression_metrics["test_used"] or not classifier_metrics["test_used"]:
        raise ValueError("Model evaluation states differ from the documented protocol")
    if policy_metrics["source_sha256"]["frozen_test_predictions"] != file_sha256(classifier_path):
        raise ValueError("Operational scenario does not match frozen classifier scores")

    selected_columns = ["order_id", "prediction_cutoff_ts", *REGRESSION_FEATURES]
    connection = duckdb.connect()
    try:
        frame = connection.read_parquet(str(test_path)).project(
            ", ".join(f'"{name}"' for name in selected_columns)
        ).df()
    finally:
        connection.close()
    if frame.order_id.isna().any() or frame.order_id.duplicated().any():
        raise ValueError("Test cohort has missing or duplicate order IDs")
    if len(frame) != classifier_metrics["test_rows"]:
        raise ValueError("Dashboard test cohort row count differs from frozen evaluation")

    frozen = pd.read_csv(classifier_path, usecols=[
        "order_id", "prediction_cutoff_ts", "delay_score",
        "alert_10pct_frozen_threshold",
    ])
    if frozen.order_id.isna().any() or frozen.order_id.duplicated().any():
        raise ValueError("Frozen classifier scores have missing or duplicate order IDs")
    if len(frozen) != len(frame) or set(frozen.order_id) != set(frame.order_id):
        raise ValueError("Classifier scores do not cover exactly the test cohort")
    model = joblib.load(regression_path)
    predicted_days = model.predict(frame.loc[:, REGRESSION_FEATURES])
    if not np.isfinite(predicted_days).all():
        raise ValueError("Regression produced nonfinite delivery durations")
    output = frame.loc[:, [
        "order_id", "prediction_cutoff_ts", "feature_customer_state",
        "feature_promised_delivery_days",
    ]].copy()
    output["predicted_delivery_days"] = predicted_days
    output = output.merge(frozen, on="order_id", how="inner", validate="one_to_one",
                          suffixes=("", "_classifier"))
    if not (pd.to_datetime(output.prediction_cutoff_ts)
            == pd.to_datetime(output.prediction_cutoff_ts_classifier)).all():
        raise ValueError("The two outputs disagree on purchase timestamps")
    output = output.drop(columns="prediction_cutoff_ts_classifier")
    policy = pd.read_csv(policy_path, usecols=[
        "order_id", "delay_score", "shift_start", "risk_rank_in_shift",
        "risk_zone", "action", "decision_available_at",
    ])
    if policy.order_id.isna().any() or policy.order_id.duplicated().any():
        raise ValueError("Operational scenario has missing or duplicate order IDs")
    if len(policy) != len(output) or set(policy.order_id) != set(output.order_id):
        raise ValueError("Operational scenario does not cover the dashboard cohort")
    output = output.merge(policy, on="order_id", how="inner", validate="one_to_one",
                          suffixes=("", "_policy"))
    if not np.allclose(output.delay_score, output.delay_score_policy, rtol=0, atol=1e-12):
        raise ValueError("Operational scenario scores differ from frozen scores")
    output = output.drop(columns="delay_score_policy")
    if output.risk_zone.value_counts().to_dict() != policy_metrics["risk_zone_counts"]:
        raise ValueError("Operational scenario risk group totals changed")
    output["alert_10pct_frozen_threshold"] = output["alert_10pct_frozen_threshold"].astype(bool)
    threshold = classifier_metrics["primary_score_threshold_frozen"]
    if not (output["alert_10pct_frozen_threshold"] == (output.delay_score >= threshold)).all():
        raise ValueError("Frozen alert decisions disagree with the selected threshold")
    output = output.rename(columns={
        "prediction_cutoff_ts": "purchase_timestamp",
        "feature_customer_state": "customer_state",
        "feature_promised_delivery_days": "promised_delivery_days",
    }).sort_values(["purchase_timestamp", "order_id"])
    output_path = model_dir / "dashboard_joint_predictions.csv"
    metadata_path = model_dir / "dashboard_joint_predictions_metadata.json"
    output.to_csv(output_path, index=False)
    metadata = {
        "scope": "retrospective July-August 2018 eventually label-eligible test orders",
        "rows": len(output),
        "regression_model": "regression_linear_asof.joblib",
        "regression_display_only_on_test": True,
        "regression_test_metrics_computed": False,
        "regression_validation_mae_days": regression_metrics["linear_regression_validation"]["mae_days"],
        "classification_model": classifier_metrics["selected_model_frozen"],
        "classification_test_roc_auc": classifier_metrics["roc_auc"],
        "classification_test_average_precision": classifier_metrics["average_precision"],
        "classification_test_alert_fraction": classifier_metrics["alert_metrics"]["10pct"]["test_alert_fraction"],
        "frozen_score_threshold": threshold,
        "score_is_calibrated_probability": False,
        "negative_regression_predictions": int((predicted_days < 0).sum()),
        "operational_scenario": "exploratory eight-hour shift ranking: top 5% manual, next to 25% automated, subject to capacity",
        "policy_shift_hours": policy_metrics["config"]["shift_hours"],
        "policy_default_manual_capacity_per_shift": policy_metrics["config"]["default_manual_capacity_per_shift"],
        "policy_risk_zone_counts": policy_metrics["risk_zone_counts"],
        "source_sha256": {
            "test_parquet": file_sha256(test_path),
            "classifier_predictions": file_sha256(classifier_path),
            "regression_model": file_sha256(regression_path),
            "policy_decisions": file_sha256(policy_path),
        },
        "output_sha256": file_sha256(output_path),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--model-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    print(json.dumps(export(args.data_dir, args.model_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

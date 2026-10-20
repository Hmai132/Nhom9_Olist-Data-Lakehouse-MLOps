"""Evaluate the frozen July 1 classifier and alert thresholds on test once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import MODEL_FEATURES, TARGET, load_cohort
from pipeline.historical_selection import BUDGETS, DECISION_ASOF, PRIMARY_BUDGET
from pipeline.ml_dataset import FEATURE_COLUMNS
from pipeline.regression_baseline import file_sha256


def evaluate(data_dir: Path, model_dir: Path) -> dict:
    selection_path = model_dir / "historical_selection_metrics.json"
    manifest_path = data_dir / "manifest.json"
    test_path = data_dir / "test.parquet"
    metrics_path = model_dir / "historical_test_metrics.json"
    predictions_path = model_dir / "historical_test_predictions.csv"
    if metrics_path.exists() or predictions_path.exists():
        raise FileExistsError("Test has already been evaluated; frozen one-time evaluation will not overwrite it")

    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if selection["test_used"] or selection["decision_asof"] != DECISION_ASOF.isoformat():
        raise ValueError("Historical model selection is not frozen before test")
    if selection["validation_unknown_labels"] > 0.01 * selection["validation_rows"]:
        raise ValueError("Too many validation labels were unknown at model selection")
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("Test feature contract differs from the frozen model")
    if manifest["test_start"] != selection["decision_asof"]:
        raise ValueError("Test start differs from the frozen decision cutoff")
    if selection["input_sha256"]["manifest"] != file_sha256(manifest_path):
        raise ValueError("Prepared dataset manifest changed since model selection")
    if selection["input_sha256"]["source_train"] != file_sha256(data_dir / "train.parquet"):
        raise ValueError("Training source changed since model selection")
    for key, filename in (
        ("historical_train", "historical_train_asof.parquet"),
        ("historical_validation_masked", "historical_validation_masked.parquet"),
    ):
        if selection["input_sha256"][key] != file_sha256(model_dir / filename):
            raise ValueError(f"Frozen {key} cohort changed since model selection")

    selected = selection["selected_model"]
    if selected not in selection["models"]:
        raise ValueError("Selected model is absent from frozen selection metrics")
    primary_key = f"{int(PRIMARY_BUDGET * 100)}pct"
    thresholds = selection["models"][selected]["fixed_thresholds"]
    threshold = thresholds[primary_key]["score_threshold"]
    if threshold != selection["selected_score_threshold"]:
        raise ValueError("Frozen primary threshold changed")
    model_path = model_dir / f"historical_{selected}.joblib"
    model = joblib.load(model_path)

    connection = duckdb.connect()
    try:
        frame = load_cohort(connection, test_path)
        validation_order_ids = set(
            connection.read_parquet(str(model_dir / "historical_validation_masked.parquet"))
            .project("order_id").df().order_id
        )
    finally:
        connection.close()
    if len(frame) != manifest["splits"]["test"]["rows"]:
        raise ValueError("Test row count changed since preparation")
    if frame.prediction_cutoff_ts.min() < pd.Timestamp(DECISION_ASOF):
        raise ValueError("Test contains purchases before the frozen decision cutoff")
    if set(frame.order_id).intersection(validation_order_ids):
        raise ValueError("Test overlaps the historical validation cohort")

    # The fitted model and fixed score thresholds are used without any refit.
    scores = model.predict_proba(frame.loc[:, MODEL_FEATURES])[:, 1]
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("Frozen classifier produced invalid scores")
    labels = frame[TARGET].to_numpy(dtype=int)
    if set(np.unique(labels)) != {0, 1}:
        raise ValueError("Test needs both delay classes for evaluation")
    predictions = pd.DataFrame({
        "order_id": frame.order_id,
        "prediction_cutoff_ts": frame.prediction_cutoff_ts,
        "delay_score": scores,
        "actual_is_delayed_calendar_day": labels,
    })
    alert_metrics = {}
    for fraction in BUDGETS:
        key = f"{int(fraction * 100)}pct"
        frozen_threshold = thresholds[key]["score_threshold"]
        alert = scores >= frozen_threshold
        tn, fp, fn, tp = (int(v) for v in confusion_matrix(labels, alert, labels=[0, 1]).ravel())
        predictions[f"alert_{key}_frozen_threshold"] = alert
        alert_metrics[key] = {
            "validation_score_threshold": frozen_threshold,
            "test_alerts": int(alert.sum()),
            "test_alert_fraction": float(alert.mean()),
            "detected_late": tp,
            "false_alarms": fp,
            "missed_late": fn,
            "true_on_time": tn,
            "precision": float(precision_score(labels, alert, zero_division=0)),
            "recall": float(recall_score(labels, alert, zero_division=0)),
            "f1": float(f1_score(labels, alert, zero_division=0)),
            "accuracy": float(accuracy_score(labels, alert)),
        }
    result = {
        "evaluation": "one-time retrospective July-August test of frozen March-April-selected model and score thresholds",
        "selected_model_frozen": selected,
        "decision_asof": selection["decision_asof"],
        "primary_alert_budget_target": PRIMARY_BUDGET,
        "primary_score_threshold_frozen": threshold,
        "test_rows": len(frame),
        "test_late": int(labels.sum()),
        "test_late_prevalence": float(labels.mean()),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "average_precision": float(average_precision_score(labels, scores)),
        "alert_metrics": alert_metrics,
        "test_used": True,
        "model_refit_on_test": False,
        "threshold_tuned_on_test": False,
        "limitations": [
            "The fixed 10% validation threshold does not guarantee a 10% cap on a future test cohort.",
            "Only eventually delivered label-eligible orders are in the retrospective test extract.",
            "Static Gold feature values cannot prove purchase-time historical availability.",
            "Earlier May-June outcomes informed exploratory feature engineering, so this is not a fully untouched prospective study.",
        ],
        "input_sha256": {
            "selection_metrics": file_sha256(selection_path),
            "frozen_model": file_sha256(model_path),
            "test_parquet": file_sha256(test_path),
        },
        "package_versions": {"numpy": np.__version__, "pandas": pd.__version__,
                             "scikit_learn": sklearn.__version__},
        "files": {"test_predictions": predictions_path.name},
    }
    predictions.to_csv(predictions_path, index=False, mode="x")
    with metrics_path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--model-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    result = evaluate(args.data_dir, args.model_dir)
    print(json.dumps({key: result[key] for key in (
        "selected_model_frozen", "test_rows", "test_late", "roc_auc",
        "average_precision", "primary_score_threshold_frozen", "test_used",
    )} | {"primary_alert_metrics": result["alert_metrics"]["10pct"]}, indent=2))


if __name__ == "__main__":
    main()

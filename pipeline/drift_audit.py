"""Diagnose the frozen classifier's validation-to-test score shift.

This script only transforms data with the already-fitted model. It never fits
features, calibrators, models or thresholds on the opened test cohort.
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
from pipeline.classification_baseline import CATEGORICAL, MODEL_FEATURES, TARGET
from pipeline.regression_baseline import file_sha256


NUMERIC = tuple(name for name in MODEL_FEATURES if name not in CATEGORICAL)


def score_summary(scores: np.ndarray, threshold: float) -> dict:
    return {
        "mean": float(scores.mean()),
        "median": float(np.median(scores)),
        "p90": float(np.quantile(scores, .90)),
        "p95": float(np.quantile(scores, .95)),
        "alert_count_at_frozen_threshold": int((scores >= threshold).sum()),
        "alert_fraction_at_frozen_threshold": float((scores >= threshold).mean()),
    }


def source_feature(transformed_name: str) -> str:
    for name in sorted(MODEL_FEATURES, key=len, reverse=True):
        if name in transformed_name:
            return name
    raise ValueError(f"Unmapped transformed feature: {transformed_name}")


def audit(data_dir: Path, model_dir: Path) -> dict:
    selection_path = model_dir / "historical_selection_metrics.json"
    test_metrics_path = model_dir / "historical_test_metrics.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    test_result = json.loads(test_metrics_path.read_text(encoding="utf-8"))
    if not test_result["test_used"] or test_result["model_refit_on_test"] or test_result["threshold_tuned_on_test"]:
        raise ValueError("Expected an already completed frozen test evaluation")
    if test_result["input_sha256"]["selection_metrics"] != file_sha256(selection_path):
        raise ValueError("Frozen selection metrics changed after test")
    selected = selection["selected_model"]
    if selected != test_result["selected_model_frozen"]:
        raise ValueError("Selected classifier differs from the one tested")
    model_path = model_dir / f"historical_{selected}.joblib"
    if test_result["input_sha256"]["frozen_model"] != file_sha256(model_path):
        raise ValueError("Frozen model changed after test")
    test_path = data_dir / "test.parquet"
    if test_result["input_sha256"]["test_parquet"] != file_sha256(test_path):
        raise ValueError("Test input changed after the one-time evaluation")
    threshold = test_result["primary_score_threshold_frozen"]
    validation_path = model_dir / "historical_validation_masked.parquet"
    connection = duckdb.connect()
    try:
        validation = connection.read_parquet(str(validation_path)).df()
        test = connection.read_parquet(str(test_path)).df()
    finally:
        connection.close()
    saved_validation = pd.read_csv(model_dir / "historical_validation_predictions.csv")
    saved_test = pd.read_csv(model_dir / test_result["files"]["test_predictions"])
    if not saved_validation.order_id.equals(validation.order_id) or not saved_test.order_id.equals(test.order_id):
        raise ValueError("Saved predictions do not align to feature cohorts")
    model = joblib.load(model_path)
    validation_scores = model.predict_proba(validation.loc[:, MODEL_FEATURES])[:, 1]
    test_scores = model.predict_proba(test.loc[:, MODEL_FEATURES])[:, 1]
    if not np.allclose(validation_scores, saved_validation[f"{selected}_score"]):
        raise ValueError("Frozen model disagrees with saved validation scores")
    if not np.allclose(test_scores, saved_test.delay_score):
        raise ValueError("Frozen model disagrees with saved test scores")

    numeric_drift = {}
    for name in NUMERIC:
        old = pd.to_numeric(validation[name], errors="coerce")
        new = pd.to_numeric(test[name], errors="coerce")
        old_median, new_median = old.median(), new.median()
        old_mean, new_mean = old.mean(), new.mean()
        pooled_sd = np.sqrt((old.var() + new.var()) / 2)
        numeric_drift[name] = {
            "validation_median": float(old_median) if pd.notna(old_median) else None,
            "test_median": float(new_median) if pd.notna(new_median) else None,
            "validation_missing_fraction": float(old.isna().mean()),
            "test_missing_fraction": float(new.isna().mean()),
            "standardized_mean_difference": float((new_mean - old_mean) / pooled_sd)
            if pd.notna(pooled_sd) and pooled_sd > 0 else None,
        }
    category_drift = {}
    for name in CATEGORICAL:
        p = validation[name].fillna("<MISSING>").astype(str).value_counts(normalize=True)
        q = test[name].fillna("<MISSING>").astype(str).value_counts(normalize=True)
        keys = p.index.union(q.index)
        category_drift[name] = {
            "total_variation_distance": float((p.reindex(keys, fill_value=0) - q.reindex(keys, fill_value=0)).abs().sum() / 2),
            "validation_missing_fraction": float(validation[name].isna().mean()),
            "test_missing_fraction": float(test[name].isna().mean()),
        }

    preprocessor = model.named_steps["preprocessing"]
    classifier = model.named_steps["classifier"]
    feature_names = preprocessor.get_feature_names_out()
    coefficient = classifier.coef_.ravel()
    old_transformed = preprocessor.transform(validation.loc[:, MODEL_FEATURES])
    new_transformed = preprocessor.transform(test.loc[:, MODEL_FEATURES])
    contributions = {}
    for index, transformed_name in enumerate(feature_names):
        original = source_feature(str(transformed_name))
        shift = float(coefficient[index] * (new_transformed[:, index].mean() - old_transformed[:, index].mean()))
        contributions[original] = contributions.get(original, 0.0) + shift
    contributions = dict(sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True))
    logit_shift = float((new_transformed @ coefficient).mean() - (old_transformed @ coefficient).mean())
    if not np.isclose(sum(contributions.values()), logit_shift):
        raise ValueError("Feature logit contributions do not reconcile")

    monthly = {}
    for name, frame, scores in (("validation", validation, validation_scores), ("test", test, test_scores)):
        by_month = pd.DataFrame({
            "month": frame.prediction_cutoff_ts.dt.to_period("M").astype(str),
            "score": scores,
            "alert": scores >= threshold,
            "promised_days": frame.feature_promised_delivery_days,
            "known_delay": frame[TARGET].map({True: 1.0, False: 0.0}),
        }).groupby("month", sort=True).agg(
            rows=("score", "size"), median_score=("score", "median"),
            alert_fraction=("alert", "mean"), promised_days_median=("promised_days", "median"),
            known_labels=("known_delay", "count"), known_late_fraction=("known_delay", "mean"),
        )
        monthly[name] = {month: {key: (int(value) if key in ("rows", "known_labels") else float(value))
                                 for key, value in row.items()}
                         for month, row in by_month.to_dict(orient="index").items()}

    known_validation = validation[TARGET].dropna()
    result = {
        "purpose": "post-test diagnosis only; no fitting or threshold changes",
        "selected_model": selected,
        "frozen_threshold": threshold,
        "validation": score_summary(validation_scores, threshold),
        "test": score_summary(test_scores, threshold),
        "validation_known_late_prevalence": float(known_validation.mean()),
        "test_late_prevalence": float(test[TARGET].mean()),
        "numeric_feature_drift": numeric_drift,
        "categorical_feature_drift": category_drift,
        "mean_logit_shift_test_minus_validation": logit_shift,
        "feature_contribution_to_mean_logit_shift": contributions,
        "monthly": monthly,
        "interpretation_limit": "Linear logit contribution describes the frozen model's score shift, not a causal explanation for delivery delays.",
        "input_sha256": {
            "selection_metrics": file_sha256(selection_path),
            "test_metrics": file_sha256(test_metrics_path),
            "validation_predictions": file_sha256(model_dir / "historical_validation_predictions.csv"),
            "test_predictions": file_sha256(model_dir / test_result["files"]["test_predictions"]),
        },
    }
    output_path = model_dir / "historical_test_drift_audit.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--model-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    result = audit(args.data_dir, args.model_dir)
    print(json.dumps({
        "validation_alert_fraction": result["validation"]["alert_fraction_at_frozen_threshold"],
        "test_alert_fraction": result["test"]["alert_fraction_at_frozen_threshold"],
        "top_logit_shift_features": list(result["feature_contribution_to_mean_logit_shift"].items())[:5],
    }, indent=2))


if __name__ == "__main__":
    main()

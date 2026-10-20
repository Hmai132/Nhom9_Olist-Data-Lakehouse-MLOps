"""Compare delay classifiers at fixed validation alert budgets.

The 10% alert budget is the project owner's operating scenario. The 5% and
20% budgets are sensitivity checks. Model selection uses validation only;
the test cohort remains sealed.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import duckdb
import joblib
import lightgbm
import numpy as np
import pandas as pd
import sklearn
from lightgbm import LGBMClassifier
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import (
    MODEL_FEATURES,
    TARGET,
    build_pipeline,
    file_sha256,
    load_cohort,
)
from pipeline.ml_dataset import FEATURE_COLUMNS


BUDGETS = (0.05, 0.10, 0.20)
PRIMARY_BUDGET = 0.10


def budget_scores(
    labels: np.ndarray, scores: np.ndarray, order_ids: np.ndarray
) -> tuple[dict, dict[float, np.ndarray]]:
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("Model generated invalid class scores")
    ranking = np.lexsort((order_ids.astype(str), -scores))
    total_late = int(labels.sum())
    prevalence = total_late / len(labels)
    budgets = {}
    flags = {}
    for fraction in BUDGETS:
        alert_count = math.floor(len(labels) * fraction)
        if alert_count < 1:
            raise ValueError("Alert budget is smaller than one order")
        chosen = ranking[:alert_count]
        selected = np.zeros(len(labels), dtype=bool)
        selected[chosen] = True
        detected_late = int(labels[chosen].sum())
        precision = detected_late / alert_count
        budgets[f"{int(fraction * 100)}pct"] = {
            "alerts": alert_count,
            "detected_late": detected_late,
            "false_alarms": alert_count - detected_late,
            "missed_late": total_late - detected_late,
            "precision": precision,
            "recall": detected_late / total_late,
            "lift_over_prevalence": precision / prevalence,
        }
        flags[fraction] = selected
    return {
        "roc_auc": float(roc_auc_score(labels, scores)),
        "alert_budgets": budgets,
    }, flags


def compare(data_dir: Path, output_dir: Path) -> dict:
    manifest_path = data_dir / "manifest.json"
    availability_path = data_dir / "label_availability.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("Prepared feature contract differs from model comparison")
    if availability["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("As-of feature contract differs from model comparison")
    if availability["target_for_delay"] != TARGET:
        raise ValueError("Expected the agreed calendar-day delay label")

    train_path = data_dir / availability["files"]["asof_train"]
    validation_path = data_dir / "validation.parquet"
    input_paths = {
        "manifest": manifest_path,
        "label_availability": availability_path,
        "train_asof_validation": train_path,
        "validation": validation_path,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    baseline_path = output_dir / "classification_asof_metrics.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline["input_sha256"] != input_hashes or baseline["target"] != TARGET:
        raise ValueError("Logistic baseline is stale; rerun pipeline.classification_baseline")
    if baseline["test_used"]:
        raise ValueError("Expected an unopened test cohort")

    connection = duckdb.connect()
    try:
        train_frame = load_cohort(connection, train_path)
        validation_frame = load_cohort(connection, validation_path)
    finally:
        connection.close()
    if len(train_frame) != availability["train_rows_asof"]:
        raise ValueError("As-of training row count changed")
    if len(validation_frame) != manifest["splits"]["validation"]["rows"]:
        raise ValueError("Validation row count changed")
    if train_frame.prediction_cutoff_ts.max() >= pd.Timestamp(availability["train_purchase_before"]):
        raise ValueError("Training purchases violate the maturity gap")
    if validation_frame.prediction_cutoff_ts.min() < pd.Timestamp(availability["validation_start"]):
        raise ValueError("Validation period starts before as-of cutoff")
    if set(train_frame.order_id).intersection(validation_frame.order_id):
        raise ValueError("Train and validation orders overlap")

    x_train = train_frame.loc[:, MODEL_FEATURES]
    y_train = train_frame[TARGET].to_numpy(dtype=int)
    x_validation = validation_frame.loc[:, MODEL_FEATURES]
    y_validation = validation_frame[TARGET].to_numpy(dtype=int)
    order_ids = validation_frame.order_id.to_numpy(dtype=str)
    if set(np.unique(y_train)) != {0, 1} or set(np.unique(y_validation)) != {0, 1}:
        raise ValueError("Both cohorts need both classes")

    logistic_model = joblib.load(output_dir / "classification_logistic_asof.joblib")
    logistic_scores = logistic_model.predict_proba(x_validation)[:, 1]
    baseline_scores_path = output_dir / "classification_asof_validation_predictions.csv"
    saved = pd.read_csv(baseline_scores_path)
    if list(saved.order_id) != list(order_ids):
        raise ValueError("Saved logistic predictions have different validation orders")
    if not np.allclose(saved.predicted_delay_probability.to_numpy(), logistic_scores):
        raise ValueError("Saved logistic predictions disagree with the model")

    positive_weight = int((y_train == 0).sum()) / int((y_train == 1).sum())
    forest = clone(build_pipeline()).set_params(
        classifier=RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=1,
        )
    )
    boosting = clone(build_pipeline()).set_params(
        classifier=LGBMClassifier(
            n_estimators=200,
            learning_rate=0.05,
            num_leaves=15,
            min_child_samples=30,
            scale_pos_weight=positive_weight,
            random_state=42,
            n_jobs=1,
            verbosity=-1,
        )
    )
    models = {
        "logistic_regression": logistic_model,
        "random_forest": forest,
        "lightgbm": boosting,
    }
    score_vectors = {"logistic_regression": logistic_scores}
    for name in ("random_forest", "lightgbm"):
        models[name].fit(x_train, y_train)
        score_vectors[name] = models[name].predict_proba(x_validation)[:, 1]
        joblib.dump(models[name], output_dir / f"classification_{name}_asof.joblib")

    comparison = {}
    flags_by_model = {}
    for name, scores in score_vectors.items():
        comparison[name], flags_by_model[name] = budget_scores(y_validation, scores, order_ids)
    key = f"{int(PRIMARY_BUDGET * 100)}pct"
    selected_model = max(
        comparison,
        key=lambda name: (
            comparison[name]["alert_budgets"][key]["detected_late"],
            comparison[name]["roc_auc"],
        ),
    )

    predictions = pd.DataFrame({
        "order_id": order_ids,
        "prediction_cutoff_ts": validation_frame.prediction_cutoff_ts,
        "actual_is_delayed_calendar_day": y_validation,
    })
    for name, scores in score_vectors.items():
        predictions[f"{name}_score"] = scores
        for fraction in BUDGETS:
            predictions[f"{name}_top_{int(fraction * 100)}pct"] = flags_by_model[name][fraction]
    predictions_path = output_dir / "classification_comparison_validation_predictions.csv"
    predictions.to_csv(predictions_path, index=False)

    result = {
        "target": TARGET,
        "source_notebooks": {
            "random_forest_and_logistic": "Phân tích dữ liệu nâng cao: Avinash Navlani (2026), Python Data Analysis",
            "lightgbm": "Data warehouse: [5] Kele Xu (2026), Data Mining Competition Practices",
        },
        "alert_budget_origin": "Project owner chose 10% operational review capacity; 5% and 20% are sensitivity checks, not textbook rules",
        "evaluation": "as-of-known training labels at 2018-05-01; retrospective validation outcomes; static Gold features not versioned",
        "train_rows": len(train_frame),
        "train_late_rows": int(y_train.sum()),
        "validation_rows": len(validation_frame),
        "validation_late_rows": int(y_validation.sum()),
        "validation_late_prevalence": float(y_validation.mean()),
        "test_used": False,
        "primary_alert_budget": PRIMARY_BUDGET,
        "top_k_rule": "floor(budget * validation rows), descending class score, order_id ascending for ties",
        "model_selection_rule": "most late orders detected at 10% budget; ROC AUC breaks ties",
        "selected_model_on_validation": selected_model,
        "models": comparison,
        "fixed_model_parameters": {
            "logistic_regression": {"class_weight": "balanced", "max_iter": 1000},
            "random_forest": {"n_estimators": 200, "min_samples_leaf": 5, "class_weight": "balanced_subsample", "random_state": 42, "n_jobs": 1},
            "lightgbm": {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 30, "scale_pos_weight_from_train": positive_weight, "random_state": 42, "n_jobs": 1},
        },
        "score_interpretation": "Class weighting distorts probability calibration; compare scores as rankings, not literal event probabilities",
        "input_sha256": input_hashes,
        "package_versions": {
            "duckdb": duckdb.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "lightgbm": lightgbm.__version__,
        },
        "files": {"validation_predictions": predictions_path.name},
    }
    (output_dir / "classification_comparison_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    print(json.dumps(compare(args.data_dir, args.output_dir), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

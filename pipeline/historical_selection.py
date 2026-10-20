"""Select a delay classifier and a fixed alert threshold before 2018-07-01.

March-April purchases form the validation cohort. Models are trained with
labels known by March 1 from orders at least 90 days old. Validation outcomes
are used only if delivery was known by July 1. The July-August test cohort is
not opened here.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import joblib
import lightgbm
import numpy as np
import pandas as pd
import sklearn
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import MODEL_FEATURES, TARGET, build_pipeline, load_cohort
from pipeline.ml_dataset import FEATURE_COLUMNS, sql_literal
from pipeline.regression_baseline import file_sha256


TRAIN_ASOF = datetime(2018, 3, 1)
VALIDATION_END = datetime(2018, 5, 1)
DECISION_ASOF = datetime(2018, 7, 1)
MATURITY_DAYS = 90
BUDGETS = (0.05, 0.10, 0.20)
PRIMARY_BUDGET = 0.10


def threshold_for_budget(scores: np.ndarray, fraction: float) -> float:
    """Set a score-only threshold with at most the budget on validation.

    A tie at the boundary is excluded in full, since an order-ID tie-break
    could not be applied to each future order independently.
    """
    count = math.floor(len(scores) * fraction)
    if not 0 < count < len(scores):
        raise ValueError("Budget must select between one and n-1 orders")
    ordered = np.sort(scores)[::-1]
    included, excluded = ordered[count - 1], ordered[count]
    if included > excluded:
        return float(included)
    return float(np.nextafter(included, np.inf))


def evaluate(scores: np.ndarray, labels: pd.Series) -> dict:
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("Invalid classification scores")
    known = labels.notna().to_numpy()
    y = labels.loc[known].to_numpy(dtype=int)
    if set(np.unique(y)) != {0, 1}:
        raise ValueError("Known validation labels need both classes")
    total_late = int(y.sum())
    metrics = {
        "known_labels": int(known.sum()),
        "unknown_labels_at_decision": int((~known).sum()),
        "known_late": total_late,
        "roc_auc_known_labels": float(roc_auc_score(y, scores[known])),
        "fixed_thresholds": {},
    }
    for fraction in BUDGETS:
        threshold = threshold_for_budget(scores, fraction)
        alert = scores >= threshold
        known_alert = alert & known
        detected = int(labels.loc[known_alert].astype(int).sum())
        known_alert_count = int(known_alert.sum())
        metrics["fixed_thresholds"][f"{int(fraction * 100)}pct"] = {
            "score_threshold": threshold,
            "validation_alerts_all": int(alert.sum()),
            "validation_alert_fraction": float(alert.mean()),
            "alerts_with_known_label": known_alert_count,
            "alerts_with_unknown_label": int((alert & ~known).sum()),
            "detected_late_known": detected,
            "false_alarms_known": known_alert_count - detected,
            "missed_late_known": total_late - detected,
            "precision_known": detected / known_alert_count if known_alert_count else None,
            "recall_known": detected / total_late,
        }
    return metrics


def select(database: Path, data_dir: Path, output_dir: Path) -> dict:
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("ML feature contract has changed")
    if manifest["test_start"] != DECISION_ASOF.isoformat():
        raise ValueError("Decision cutoff differs from the sealed test start")
    source_path = data_dir / "train.parquet"
    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "historical_train_asof.parquet"
    validation_path = output_dir / "historical_validation_masked.parquet"
    train_cutoff = sql_literal(TRAIN_ASOF.isoformat(sep=" "))
    purchase_end = sql_literal((TRAIN_ASOF - timedelta(days=MATURITY_DAYS)).isoformat(sep=" "))
    val_end = sql_literal(VALIDATION_END.isoformat(sep=" "))
    decision_cutoff = sql_literal(DECISION_ASOF.isoformat(sep=" "))
    source = sql_literal(str(source_path))
    feature_names = ", ".join(f"t.{name}" for name in FEATURE_COLUMNS)
    target_names = ("target_actual_delivery_days", "target_is_delayed_timestamp")
    other_targets = ", ".join(f"t.{name}" for name in target_names)
    connection = duckdb.connect(str(database), read_only=True)
    try:
        train_query = f"""
            SELECT t.order_id, t.prediction_cutoff_ts, {feature_names},
                   {other_targets}, t.{TARGET}
            FROM read_parquet({source}) t
            JOIN gold.fact_delivery_performance f USING (order_id)
            WHERE t.prediction_cutoff_ts < {purchase_end}
              AND f.order_delivered_customer_date < {train_cutoff}
            ORDER BY t.prediction_cutoff_ts, t.order_id
        """
        validation_query = f"""
            SELECT t.order_id, t.prediction_cutoff_ts, {feature_names},
                   CASE WHEN f.order_delivered_customer_date < {decision_cutoff}
                        THEN t.{TARGET} ELSE NULL END AS {TARGET}
            FROM read_parquet({source}) t
            JOIN gold.fact_delivery_performance f USING (order_id)
            WHERE t.prediction_cutoff_ts >= {train_cutoff}
              AND t.prediction_cutoff_ts < {val_end}
            ORDER BY t.prediction_cutoff_ts, t.order_id
        """
        connection.execute(f"COPY ({train_query}) TO {sql_literal(str(train_path))} (FORMAT PARQUET)")
        connection.execute(f"COPY ({validation_query}) TO {sql_literal(str(validation_path))} (FORMAT PARQUET)")
        train = load_cohort(connection, train_path)
        validation = connection.read_parquet(str(validation_path)).df()
    finally:
        connection.close()
    if train.order_id.duplicated().any() or validation.order_id.duplicated().any():
        raise ValueError("Historical cohort contains duplicate orders")
    if set(train.order_id).intersection(validation.order_id):
        raise ValueError("Historical train and validation overlap")
    if train.prediction_cutoff_ts.max() >= pd.Timestamp(TRAIN_ASOF - timedelta(days=MATURITY_DAYS)):
        raise ValueError("Train maturity gap violated")
    if not validation.prediction_cutoff_ts.between(TRAIN_ASOF, VALIDATION_END, inclusive="left").all():
        raise ValueError("Historical validation period violated")
    if validation[TARGET].isna().mean() > 0.01:
        raise ValueError("More than 1% of historical validation labels unknown at decision")

    x_train = train.loc[:, MODEL_FEATURES]
    y_train = train[TARGET].to_numpy(dtype=int)
    x_validation = validation.loc[:, MODEL_FEATURES]
    negative_positive_ratio = int((y_train == 0).sum()) / int((y_train == 1).sum())
    models = {
        "logistic_regression": build_pipeline(),
        "random_forest": build_pipeline().set_params(classifier=RandomForestClassifier(
            n_estimators=200, min_samples_leaf=5, class_weight="balanced_subsample",
            random_state=42, n_jobs=1,
        )),
        "lightgbm": build_pipeline().set_params(classifier=LGBMClassifier(
            n_estimators=200, learning_rate=0.05, num_leaves=15,
            min_child_samples=30, scale_pos_weight=negative_positive_ratio,
            random_state=42, n_jobs=1, verbosity=-1,
        )),
    }
    metrics = {}
    predictions = pd.DataFrame({
        "order_id": validation.order_id,
        "prediction_cutoff_ts": validation.prediction_cutoff_ts,
        "known_delay_label_asof_2018_07_01": validation[TARGET],
    })
    for name, model in models.items():
        model.fit(x_train, y_train)
        scores = model.predict_proba(x_validation)[:, 1]
        metrics[name] = evaluate(scores, validation[TARGET])
        predictions[f"{name}_score"] = scores
        for fraction in BUDGETS:
            key = f"{int(fraction * 100)}pct"
            predictions[f"{name}_alert_{key}"] = scores >= metrics[name]["fixed_thresholds"][key]["score_threshold"]
        joblib.dump(model, output_dir / f"historical_{name}.joblib")
    primary = "10pct"
    selected = max(models, key=lambda name: (
        metrics[name]["fixed_thresholds"][primary]["detected_late_known"],
        metrics[name]["roc_auc_known_labels"],
    ))
    prediction_path = output_dir / "historical_validation_predictions.csv"
    predictions.to_csv(prediction_path, index=False)
    result = {
        "protocol": "as-of train 2018-03-01, March-April validation; choose with labels known 2018-07-01",
        "decision_asof": DECISION_ASOF.isoformat(),
        "train_asof": TRAIN_ASOF.isoformat(),
        "train_purchase_before": (TRAIN_ASOF - timedelta(days=MATURITY_DAYS)).isoformat(),
        "validation_start": TRAIN_ASOF.isoformat(),
        "validation_end": VALIDATION_END.isoformat(),
        "maturity_gap_days": MATURITY_DAYS,
        "label_available_proxy": "order_delivered_customer_date, conservatively",
        "train_rows": len(train),
        "train_late": int(y_train.sum()),
        "validation_rows": len(validation),
        "validation_known_labels": int(validation[TARGET].notna().sum()),
        "validation_unknown_labels": int(validation[TARGET].isna().sum()),
        "primary_alert_budget_target": PRIMARY_BUDGET,
        "fixed_threshold_rule": "score >= validation threshold; boundary ties fully excluded so validation rate <= budget",
        "model_selection_rule": "most known late orders detected at 10% validation budget; known-label ROC AUC breaks ties",
        "selected_model": selected,
        "selected_score_threshold": metrics[selected]["fixed_thresholds"][primary]["score_threshold"],
        "models": metrics,
        "score_interpretation": "weighted-class scores are ranking scores, not calibrated event probabilities",
        "limitations": [
            "Fixed threshold targets at most 10% on historical validation; future alert rate is not guaranteed at or below 10%.",
            "Gold features are a static historical extract, not purchase-time versioned records.",
            "Only eventually label-eligible delivered orders appear in the retrospective source cohort.",
            "Unknown validation labels may affect close model rankings; inspect count and score margins.",
            "Earlier May-June outcomes were used during exploratory feature engineering; this replay is not a fully untouched prospective study.",
        ],
        "test_used": False,
        "input_sha256": {
            "manifest": file_sha256(manifest_path),
            "source_train": file_sha256(source_path),
            "historical_train": file_sha256(train_path),
            "historical_validation_masked": file_sha256(validation_path),
        },
        "package_versions": {"duckdb": duckdb.__version__, "numpy": np.__version__,
                             "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
                             "lightgbm": lightgbm.__version__},
        "files": {"validation_predictions": prediction_path.name},
    }
    (output_dir / "historical_selection_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/warehouse/olist.duckdb")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    result = select(args.database, args.data_dir, args.output_dir)
    print(json.dumps({key: result[key] for key in (
        "train_rows", "train_late", "validation_rows", "validation_known_labels",
        "validation_unknown_labels", "selected_model", "selected_score_threshold", "test_used",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

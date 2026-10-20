"""Post-test feature ablation with pre-July chronological, as-of-known labels.

This study does not read July-August cohorts or replace the frozen v1 model.
It compares purchase-month representations and the promised-delivery feature
using January-April 2018 purchase cohorts. Each fold refits preprocessing on
historically available training labels only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import CATEGORICAL, MODEL_FEATURES, OTHER_NUMERIC, TARGET
from pipeline.ml_features import LOG_FEATURES
from pipeline.ml_dataset import FEATURE_COLUMNS, sql_literal
from pipeline.regression_baseline import file_sha256


MONTH = "feature_purchase_month"
PROMISED = "feature_promised_delivery_days"
VARIANTS = ("v1_numeric_month", "no_month", "onehot_month", "cyclic_month", "no_promised_days")
FOLD_MONTHS = ("2018-01", "2018-02", "2018-03", "2018-04")
MATURITY_DAYS = 90
RED_FRACTION = 0.05


def features_for_variant(frame: pd.DataFrame, variant: str) -> pd.DataFrame:
    if variant not in VARIANTS:
        raise ValueError(f"Unknown variant: {variant}")
    result = frame.loc[:, MODEL_FEATURES].copy()
    if variant == "cyclic_month":
        angle = 2 * np.pi * (result[MONTH].astype(float) - 1) / 12
        result["purchase_month_sin"] = np.sin(angle)
        result["purchase_month_cos"] = np.cos(angle)
        result = result.drop(columns=MONTH)
    elif variant == "no_month":
        result = result.drop(columns=MONTH)
    elif variant == "no_promised_days":
        result = result.drop(columns=PROMISED)
    return result


def build_variant(variant: str) -> Pipeline:
    if variant not in VARIANTS:
        raise ValueError(f"Unknown variant: {variant}")
    numeric_columns = [name for name in OTHER_NUMERIC if not (
        (variant in ("no_month", "onehot_month", "cyclic_month") and name == MONTH)
        or (variant == "no_promised_days" and name == PROMISED)
    )]
    if variant == "cyclic_month":
        numeric_columns += ["purchase_month_sin", "purchase_month_cos"]
    categorical_columns = list(CATEGORICAL)
    if variant == "onehot_month":
        categorical_columns.append(MONTH)
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scaler", StandardScaler()),
    ])
    log_numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("log1p", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    return Pipeline([
        ("preprocessing", ColumnTransformer([
            ("numeric", numeric, numeric_columns),
            ("log_numeric", log_numeric, list(LOG_FEATURES)),
            ("categorical", categorical, categorical_columns),
        ], remainder="drop")),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000)),
    ])


def red_band_metrics(ids: pd.Series, timestamps: pd.Series, scores: np.ndarray,
                     labels: pd.Series) -> dict:
    """Rank within completed eight-hour shifts, then inspect known labels."""
    decisions = pd.DataFrame({
        "order_id": ids.to_numpy(), "timestamp": timestamps.to_numpy(),
        "score": scores, "label": labels.to_numpy(),
    })
    decisions["shift"] = pd.to_datetime(decisions.timestamp).dt.floor("8h")
    decisions = decisions.sort_values(
        ["shift", "score", "order_id"], ascending=[True, False, True], kind="mergesort"
    )
    groups = decisions.groupby("shift", sort=False)
    rank = groups.cumcount() + 1
    red = rank <= np.floor(groups.order_id.transform("size") * RED_FRACTION).astype(int)
    known = decisions.label.notna()
    late = decisions.label.fillna(False).astype(bool)
    red_known = red & known
    known_late = int((known & late).sum())
    detected = int((red_known & late).sum())
    return {
        "shifts": int(decisions["shift"].nunique()),
        "red_orders": int(red.sum()),
        "red_fraction": float(red.mean()),
        "red_with_known_label": int(red_known.sum()),
        "red_with_unknown_label": int((red & ~known).sum()),
        "known_late_in_red": detected,
        "precision_known": detected / int(red_known.sum()) if red_known.any() else None,
        "recall_known": detected / known_late if known_late else None,
    }


def evaluate_fold(frame: pd.DataFrame, month: str, variant: str) -> dict:
    start = pd.Timestamp(f"{month}-01")
    end = start + pd.DateOffset(months=1)
    label_cutoff = end + pd.DateOffset(months=2)
    train = frame.loc[
        frame.prediction_cutoff_ts.lt(start - pd.Timedelta(days=MATURITY_DAYS))
        & frame.label_available_ts.lt(start)
    ]
    assessment = frame.loc[
        frame.prediction_cutoff_ts.ge(start) & frame.prediction_cutoff_ts.lt(end)
    ].copy()
    assessment[TARGET] = assessment[TARGET].astype("boolean").mask(
        assessment.label_available_ts.ge(label_cutoff)
    )
    known = assessment[TARGET].notna()
    if not len(train) or not len(assessment) or set(train[TARGET].astype(int)) != {0, 1}:
        raise ValueError(f"Insufficient train/assessment data in {month}")
    if set(assessment.loc[known, TARGET].astype(int)) != {0, 1}:
        raise ValueError(f"Insufficient known label classes in {month}")
    if not (train.prediction_cutoff_ts < start - pd.Timedelta(days=MATURITY_DAYS)).all():
        raise ValueError("Training maturity constraint violated")
    if not (train.label_available_ts < start).all():
        raise ValueError("Training labels available after fold start")
    model = build_variant(variant)
    model.fit(features_for_variant(train, variant), train[TARGET].astype(int))
    scores = model.predict_proba(features_for_variant(assessment, variant))[:, 1]
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("Invalid score")
    y = assessment.loc[known, TARGET].astype(int).to_numpy()
    known_scores = scores[known.to_numpy()]
    return {
        "month": month, "variant": variant,
        "train_asof": start.isoformat(),
        "train_purchase_before": (start - pd.Timedelta(days=MATURITY_DAYS)).isoformat(),
        "assessment_label_cutoff": label_cutoff.isoformat(),
        "train_rows": int(len(train)), "train_late_rate": float(train[TARGET].mean()),
        "assessment_rows": int(len(assessment)), "known_labels": int(known.sum()),
        "unknown_labels": int((~known).sum()), "known_late_rate": float(y.mean()),
        "mean_score_all": float(scores.mean()),
        "mean_score_known": float(known_scores.mean()),
        "roc_auc_known": float(roc_auc_score(y, known_scores)),
        "average_precision_known": float(average_precision_score(y, known_scores)),
        "brier_known": float(brier_score_loss(y, known_scores)),
        "red_band": red_band_metrics(
            assessment.order_id, assessment.prediction_cutoff_ts, scores, assessment[TARGET]
        ),
    }


def run(database: Path, data_dir: Path, output_dir: Path) -> dict:
    manifest_path = data_dir / "manifest.json"
    selection_path = output_dir / "historical_selection_metrics.json"
    test_metrics_path = output_dir / "historical_test_metrics.json"
    train_path = data_dir / "train.parquet"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("Feature contract changed")
    if manifest["validation_start"] != "2018-05-01T00:00:00":
        raise ValueError("Expected train extract to end before May 2018")
    if selection["input_sha256"]["source_train"] != file_sha256(train_path):
        raise ValueError("Frozen v1 training source changed")
    if not test_metrics_path.exists():
        raise ValueError("This is explicitly a post-test exploratory study")
    test_metrics = json.loads(test_metrics_path.read_text(encoding="utf-8"))
    if not test_metrics["test_used"]:
        raise ValueError("Expected opened v1 test status")
    # Only the pre-May train parquet and its delivery timestamps are loaded.
    source = sql_literal(str(train_path))
    connection = duckdb.connect(str(database), read_only=True)
    try:
        frame = connection.execute(f"""
            SELECT t.*, f.order_delivered_customer_date AS label_available_ts
            FROM read_parquet({source}) t
            JOIN gold.fact_delivery_performance f USING (order_id)
            ORDER BY t.prediction_cutoff_ts, t.order_id
        """).df()
    finally:
        connection.close()
    if len(frame) != manifest["splits"]["train"]["rows"] or frame.order_id.duplicated().any():
        raise ValueError("Pre-May cohort does not reconcile with manifest")
    if not frame.prediction_cutoff_ts.lt(pd.Timestamp("2018-05-01")).all():
        raise ValueError("Source contains May or later purchases")
    if frame.label_available_ts.isna().any() or (frame.label_available_ts < frame.prediction_cutoff_ts).any():
        raise ValueError("Invalid label availability timestamp")
    if frame.loc[:, LOG_FEATURES].lt(0).any().any():
        raise ValueError("Negative log-transform input")
    rows = [evaluate_fold(frame, month, variant)
            for month in FOLD_MONTHS for variant in VARIANTS]
    baseline = {(row["month"]): row for row in rows if row["variant"] == VARIANTS[0]}
    summaries = {}
    for variant in VARIANTS:
        subset = [row for row in rows if row["variant"] == variant]
        summaries[variant] = {
            "mean_roc_auc": float(np.mean([row["roc_auc_known"] for row in subset])),
            "mean_average_precision": float(np.mean([row["average_precision_known"] for row in subset])),
            "mean_brier": float(np.mean([row["brier_known"] for row in subset])),
            "total_known_late_in_red": sum(row["red_band"]["known_late_in_red"] for row in subset),
            "total_red_with_known_label": sum(row["red_band"]["red_with_known_label"] for row in subset),
            "mean_auc_delta_vs_v1": float(np.mean([
                row["roc_auc_known"] - baseline[row["month"]]["roc_auc_known"] for row in subset
            ])),
        }
    result = {
        "scope": "post-test exploratory pre-July feature ablation; not independent model validation",
        "variants": list(VARIANTS), "fold_months": list(FOLD_MONTHS),
        "label_rule": "only orders delivered before two calendar months after assessment month end are scored",
        "maturity_gap_days": MATURITY_DAYS,
        "red_rule": "top floor(5% of each completed eight-hour shift), ranked without labels",
        "baseline_note": "v1_numeric_month uses the same pipeline specification as v1, refitted independently at each fold start",
        "source_alignment": "NotebookLM Python Data Analysis: train-only preprocessing, ColumnTransformer, OneHotEncoder, chronological validation; cyclic encoding and delayed-label handling are project extensions",
        "folds": rows, "summary": summaries,
        "limitations": [
            "July-August test was previously opened and its drift motivated these variants; no fresh unbiased test remains in this Olist extract.",
            "Static Gold features cannot prove historical purchase-time feature versions.",
            "Retrospective extract excludes orders that never became eligible for a delivery label.",
            "Late labels are masked by delivery timestamp; missing labels may bias known-label metrics.",
            "Red ranking is available at shift close, not immediately on order placement.",
            "Brier scores describe weighted-class outputs and should not be treated as calibrated probabilities.",
        ],
        "test_rows_read": 0,
        "input_sha256": {
            "manifest": file_sha256(manifest_path),
            "train_parquet": file_sha256(train_path),
            "historical_selection_metrics": file_sha256(selection_path),
            "historical_test_metrics": file_sha256(test_metrics_path),
        },
        "package_versions": {"duckdb": duckdb.__version__, "numpy": np.__version__,
                             "pandas": pd.__version__, "scikit_learn": sklearn.__version__},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "temporal_feature_experiment_metrics.json"
    if output_path.exists():
        raise FileExistsError(f"Exploratory result already exists: {output_path}")
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/warehouse/olist.duckdb")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    result = run(args.database, args.data_dir, args.output_dir)
    print(json.dumps({"fold_months": result["fold_months"], "summary": result["summary"]}, indent=2))


if __name__ == "__main__":
    main()

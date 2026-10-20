"""Fit a purchase-time calendar-day delay classifier on as-of-known labels.

The May-June validation period is used for evaluation only. The test cohort
remains sealed, and the decision threshold stays at the default 0.5.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from pipeline.bronze import PROJECT_ROOT
from pipeline.ml_dataset import FEATURE_COLUMNS
from pipeline.ml_features import LOG_FEATURES
from pipeline.regression_baseline import file_sha256


TARGET = "target_is_delayed_calendar_day"
CATEGORICAL = ("feature_customer_state",)
EXCLUDED = ("feature_customer_zip_code_prefix",)
NUMERIC = tuple(name for name in FEATURE_COLUMNS if name not in CATEGORICAL + EXCLUDED)
MODEL_FEATURES = (*NUMERIC, *CATEGORICAL)
OTHER_NUMERIC = tuple(name for name in NUMERIC if name not in LOG_FEATURES)


def load_cohort(connection: duckdb.DuckDBPyConnection, path: Path) -> pd.DataFrame:
    frame = connection.read_parquet(str(path)).df()
    required = {"order_id", "prediction_cutoff_ts", TARGET, *MODEL_FEATURES}
    if missing := required - set(frame.columns):
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if frame.order_id.duplicated().any() or frame.order_id.isna().any():
        raise ValueError(f"{path.name} has missing or duplicate order IDs")
    if frame[TARGET].isna().any() or not frame[TARGET].isin([False, True, 0, 1]).all():
        raise ValueError(f"{path.name} has invalid delay labels")
    if frame.loc[:, LOG_FEATURES].lt(0).any().any():
        raise ValueError(f"{path.name} has negative log-transform inputs")
    return frame


def build_pipeline() -> Pipeline:
    numeric = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", StandardScaler()),
        ]
    )
    log_numeric = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("log1p", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    preprocessing = ColumnTransformer(
        transformers=[
            ("numeric", numeric, list(OTHER_NUMERIC)),
            ("log_numeric", log_numeric, list(LOG_FEATURES)),
            ("categorical", categorical, list(CATEGORICAL)),
        ],
        remainder="drop",
    )
    return Pipeline(
        steps=[
            ("preprocessing", preprocessing),
            ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ]
    )


def classification_scores(y_true: np.ndarray, y_pred: np.ndarray, probability: np.ndarray) -> dict:
    tn, fp, fn, tp = (int(value) for value in confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel())
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_late": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall_late": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1_late": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "confusion_matrix": {"true_on_time": tn, "false_alarm": fp, "missed_late": fn, "detected_late": tp},
        "predicted_late_count": int(y_pred.sum()),
    }


def train(data_dir: Path, output_dir: Path) -> dict:
    manifest_path = data_dir / "manifest.json"
    availability_path = data_dir / "label_availability.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("Prepared feature contract differs from classifier code")
    if availability["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("As-of feature contract differs from classifier code")
    if manifest["validation_start"] != availability["validation_start"]:
        raise ValueError("As-of cutoff differs from the validation period")
    if availability["target_for_delay"] != TARGET:
        raise ValueError("As-of delay target differs from the agreed calendar-day label")

    train_path = data_dir / availability["files"]["asof_train"]
    validation_path = data_dir / "validation.parquet"
    connection = duckdb.connect()
    try:
        train_frame = load_cohort(connection, train_path)
        validation_frame = load_cohort(connection, validation_path)
    finally:
        connection.close()
    if len(train_frame) != availability["train_rows_asof"]:
        raise ValueError("Train count disagrees with as-of report")
    if len(validation_frame) != manifest["splits"]["validation"]["rows"]:
        raise ValueError("Validation count disagrees with manifest")
    if train_frame.prediction_cutoff_ts.max() >= pd.Timestamp(availability["train_purchase_before"]):
        raise ValueError("Train purchases violate the maturity gap")
    if validation_frame.prediction_cutoff_ts.min() < pd.Timestamp(availability["validation_start"]):
        raise ValueError("Validation starts before the as-of training cutoff")
    if set(train_frame.order_id).intersection(validation_frame.order_id):
        raise ValueError("Train and validation order IDs overlap")

    x_train = train_frame.loc[:, MODEL_FEATURES]
    y_train = train_frame[TARGET].to_numpy(dtype=int)
    x_validation = validation_frame.loc[:, MODEL_FEATURES]
    y_validation = validation_frame[TARGET].to_numpy(dtype=int)
    if set(np.unique(y_train)) != {0, 1} or set(np.unique(y_validation)) != {0, 1}:
        raise ValueError("Both cohorts need both classes for classification metrics")

    majority = DummyClassifier(strategy="most_frequent")
    majority.fit(x_train, y_train)
    majority_pred = majority.predict(x_validation)
    majority_prob = majority.predict_proba(x_validation)[:, 1]

    model = build_pipeline()
    model.fit(x_train, y_train)
    predictions = model.predict(x_validation)
    probabilities = model.predict_proba(x_validation)[:, 1]
    if not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError("Classifier produced invalid probabilities")

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "classification_logistic_asof.joblib"
    joblib.dump(model, model_path)
    predictions_path = output_dir / "classification_asof_validation_predictions.csv"
    pd.DataFrame({
        "order_id": validation_frame.order_id,
        "prediction_cutoff_ts": validation_frame.prediction_cutoff_ts,
        "actual_is_delayed_calendar_day": y_validation,
        "predicted_delay_probability": probabilities,
        "predicted_is_delayed_calendar_day": predictions,
    }).to_csv(predictions_path, index=False)

    result = {
        "model": "LogisticRegression with train-fitted Pipeline/ColumnTransformer",
        "source_book": "Avinash Navlani (2026), Python Data Analysis, NotebookLM Phân tích dữ liệu nâng cao",
        "target": TARGET,
        "positive_class": "customer delivery calendar date after estimated delivery calendar date",
        "evaluation": "as-of-known training labels at validation start; retrospective validation outcomes; static features are not versioned",
        "validation_start": availability["validation_start"],
        "maturity_gap_days": availability["maturity_gap_days"],
        "train_rows": len(train_frame),
        "train_late_rows": int(y_train.sum()),
        "validation_rows": len(validation_frame),
        "validation_late_rows": int(y_validation.sum()),
        "test_used": False,
        "classification_threshold": 0.5,
        "class_weight": "balanced",
        "numeric_features": list(NUMERIC),
        "categorical_features": list(CATEGORICAL),
        "excluded_baseline_features": list(EXCLUDED),
        "feature_availability_assumptions": manifest["feature_availability_assumptions"],
        "log1p_features": list(LOG_FEATURES),
        "majority_benchmark_validation": classification_scores(y_validation, majority_pred, majority_prob),
        "logistic_regression_validation": classification_scores(y_validation, predictions, probabilities),
        "input_sha256": {
            "manifest": file_sha256(manifest_path),
            "label_availability": file_sha256(availability_path),
            "train_asof_validation": file_sha256(train_path),
            "validation": file_sha256(validation_path),
        },
        "package_versions": {
            "duckdb": duckdb.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    (output_dir / "classification_asof_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    print(json.dumps(train(args.data_dir, args.output_dir), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

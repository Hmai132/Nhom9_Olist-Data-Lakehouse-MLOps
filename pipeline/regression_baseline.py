"""Fit a purchase-time linear regression baseline with as-of-known labels.

Only the May 1 as-of training cohort fits preprocessing and model parameters.
The May-June validation cohort is evaluated; the test cohort remains sealed.
Gold features come from a static extract, so this is not a full deployment replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from pipeline.bronze import PROJECT_ROOT
from pipeline.ml_dataset import FEATURE_COLUMNS


TARGET = "target_actual_delivery_days"
CATEGORICAL = ("feature_customer_state",)
BASELINE_EXCLUDED = ("feature_customer_zip_code_prefix",)
NUMERIC = tuple(
    name for name in FEATURE_COLUMNS if name not in CATEGORICAL + BASELINE_EXCLUDED
)
MODEL_FEATURES = (*NUMERIC, *CATEGORICAL)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_cohort(connection: duckdb.DuckDBPyConnection, path: Path) -> pd.DataFrame:
    frame = connection.read_parquet(str(path)).df()
    required = {"order_id", "prediction_cutoff_ts", TARGET, *MODEL_FEATURES}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if frame.order_id.duplicated().any():
        raise ValueError(f"{path.name} has duplicate order IDs")
    if frame[TARGET].isna().any() or not np.isfinite(frame[TARGET].to_numpy()).all():
        raise ValueError(f"{path.name} has invalid regression labels")
    return frame


def build_pipeline() -> Pipeline:
    numeric = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
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
            ("numeric", numeric, list(NUMERIC)),
            ("categorical", categorical, list(CATEGORICAL)),
        ],
        remainder="drop",
    )
    return Pipeline(
        steps=[("preprocessing", preprocessing), ("regressor", LinearRegression())]
    )


def scores(y_true: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    return {
        "mae_days": float(mean_absolute_error(y_true, predictions)),
        "rmse_days": float(np.sqrt(mean_squared_error(y_true, predictions))),
        "r2": float(r2_score(y_true, predictions)),
    }


def train(data_dir: Path, output_dir: Path) -> dict:
    manifest_path = data_dir / "manifest.json"
    availability_path = data_dir / "label_availability.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    if list(FEATURE_COLUMNS) != manifest["feature_columns"]:
        raise ValueError("Prepared feature contract differs from the model code")
    if list(FEATURE_COLUMNS) != availability["feature_columns"]:
        raise ValueError("As-of feature contract differs from the model code")
    if manifest["validation_start"] != availability["validation_start"]:
        raise ValueError("As-of cutoff differs from the validation start")

    connection = duckdb.connect()
    train_path = data_dir / availability["files"]["asof_train"]
    validation_path = data_dir / "validation.parquet"
    train_frame = load_cohort(connection, train_path)
    validation_frame = load_cohort(connection, validation_path)
    connection.close()
    if len(train_frame) != availability["train_rows_asof"]:
        raise ValueError("Training row count disagrees with as-of report")
    if len(validation_frame) != manifest["splits"]["validation"]["rows"]:
        raise ValueError("Validation row count disagrees with manifest")
    if train_frame.prediction_cutoff_ts.max() >= pd.Timestamp(availability["train_purchase_before"]):
        raise ValueError("Training purchases violate the maturity gap")
    if train_frame.prediction_cutoff_ts.max() >= validation_frame.prediction_cutoff_ts.min():
        raise ValueError("Training and validation purchase periods overlap")
    if set(train_frame.order_id).intersection(validation_frame.order_id):
        raise ValueError("Training and validation order IDs overlap")

    x_train = train_frame.loc[:, MODEL_FEATURES]
    y_train = train_frame[TARGET].to_numpy(dtype=float)
    x_validation = validation_frame.loc[:, MODEL_FEATURES]
    y_validation = validation_frame[TARGET].to_numpy(dtype=float)
    baseline_median = float(np.median(y_train))
    baseline_predictions = np.full(len(y_validation), baseline_median)

    model = build_pipeline()
    model.fit(x_train, y_train)
    predictions = model.predict(x_validation)
    if not np.isfinite(predictions).all():
        raise ValueError("Model generated nonfinite predictions")

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "regression_linear_asof.joblib"
    joblib.dump(model, model_path)
    pd.DataFrame(
        {
            "order_id": validation_frame.order_id,
            "prediction_cutoff_ts": validation_frame.prediction_cutoff_ts,
            "actual_delivery_days": y_validation,
            "predicted_delivery_days": predictions,
        }
    ).to_csv(output_dir / "regression_asof_validation_predictions.csv", index=False)

    result = {
        "model": "LinearRegression with train-fitted Pipeline/ColumnTransformer",
        "source_book": "Avinash Navlani (2026), Python Data Analysis, NotebookLM Phân tích dữ liệu nâng cao",
        "target": TARGET,
        "evaluation": "as-of-known training labels at validation start; retrospective validation outcomes; static features are not versioned",
        "validation_start": availability["validation_start"],
        "maturity_gap_days": availability["maturity_gap_days"],
        "train_rows": len(train_frame),
        "validation_rows": len(validation_frame),
        "test_used": False,
        "numeric_features": list(NUMERIC),
        "categorical_features": list(CATEGORICAL),
        "excluded_baseline_features": list(BASELINE_EXCLUDED),
        "feature_availability_assumptions": manifest["feature_availability_assumptions"],
        "train_target_median_days": baseline_median,
        "median_benchmark_validation": scores(y_validation, baseline_predictions),
        "linear_regression_validation": scores(y_validation, predictions),
        "negative_prediction_count": int((predictions < 0).sum()),
        "minimum_prediction_days": float(predictions.min()),
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
    (output_dir / "regression_asof_metrics.json").write_text(
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

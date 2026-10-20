"""Audit purchase-time ML features using train and validation inputs only.

All distribution and target diagnostics are computed on the as-of training
cohort. Validation contributes only unlabeled drift/missingness checks. The
test cohort is never opened.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import CATEGORICAL, EXCLUDED, MODEL_FEATURES, TARGET
from pipeline.ml_dataset import FEATURE_COLUMNS
from pipeline.ml_features import LOG_FEATURES
from pipeline.regression_baseline import file_sha256


def describe_numeric(series: pd.Series) -> dict:
    values = pd.to_numeric(series, errors="coerce")
    finite = values.replace([np.inf, -np.inf], np.nan).dropna()
    result = {
        "missing": int(values.isna().sum()),
        "missing_fraction": float(values.isna().mean()),
        "nonfinite": int((values.notna() & ~np.isfinite(values)).sum()),
        "distinct": int(finite.nunique()),
        "zero_fraction": float((finite == 0).mean()) if len(finite) else None,
    }
    if len(finite):
        quantiles = finite.quantile([0, .01, .25, .5, .75, .95, .99, 1])
        result["quantiles"] = {str(q): float(v) for q, v in quantiles.items()}
        result["skew"] = float(finite.skew()) if len(finite) > 2 and finite.nunique() > 1 else None
        result["nonnegative"] = bool((finite >= 0).all())
        if result["nonnegative"] and finite.nunique() > 1:
            result["log1p_skew"] = float(np.log1p(finite).skew())
    return result


def audit(data_dir: Path, output_path: Path) -> dict:
    manifest_path = data_dir / "manifest.json"
    availability_path = data_dir / "label_availability.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("ML feature contract has changed")
    if availability["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("As-of feature contract has changed")
    train_path = data_dir / availability["files"]["asof_train"]
    validation_path = data_dir / "validation.parquet"
    connection = duckdb.connect()
    try:
        train = connection.read_parquet(str(train_path)).df()
        validation = connection.read_parquet(str(validation_path)).df()
    finally:
        connection.close()
    if len(train) != availability["train_rows_asof"]:
        raise ValueError("As-of train row count changed")
    if len(validation) != manifest["splits"]["validation"]["rows"]:
        raise ValueError("Validation row count changed")
    if set(train.order_id).intersection(validation.order_id):
        raise ValueError("Train and validation orders overlap")
    if train[TARGET].isna().any():
        raise ValueError("As-of train contains missing targets")

    numeric = [name for name in FEATURE_COLUMNS if name not in CATEGORICAL]
    features = {}
    for name in numeric:
        train_stats = describe_numeric(train[name])
        val_stats = describe_numeric(validation[name])
        # Descriptive association only; no feature is selected using validation labels.
        x = pd.to_numeric(train[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
        association = x.corr(train[TARGET].astype(int), method="spearman")
        features[name] = {
            "used_by_current_models": name in MODEL_FEATURES,
            "train": train_stats,
            "validation_unlabeled": {
                "missing": val_stats["missing"],
                "missing_fraction": val_stats["missing_fraction"],
                "nonfinite": val_stats["nonfinite"],
                "median": val_stats.get("quantiles", {}).get("0.5"),
                "p99": val_stats.get("quantiles", {}).get("0.99"),
            },
            "train_spearman_with_delay": float(association) if pd.notna(association) else None,
        }
    for name in CATEGORICAL:
        counts = train[name].fillna("<MISSING>").astype(str).value_counts()
        features[name] = {
            "used_by_current_models": name in MODEL_FEATURES,
            "train": {
                "missing": int(train[name].isna().sum()),
                "missing_fraction": float(train[name].isna().mean()),
                "distinct": int(train[name].nunique(dropna=True)),
                "top_categories": {str(k): int(v) for k, v in counts.head(10).items()},
            },
            "validation_unlabeled": {
                "missing": int(validation[name].isna().sum()),
                "missing_fraction": float(validation[name].isna().mean()),
                "unseen_category_rows": int((~validation[name].isin(train[name].dropna())).sum()),
            },
        }
    for name in LOG_FEATURES:
        if not features[name]["train"]["nonnegative"] or not bool((validation[name].dropna() >= 0).all()):
            raise ValueError(f"Log-transform feature {name} has negative values")
    result = {
        "purpose": "train-only feature diagnostics; validation input drift; no test access",
        "source_notebook": "Phan tich du lieu nang cao / Avinash Navlani (2026) Python Data Analysis: data preparation and feature engineering",
        "train_rows": len(train),
        "validation_rows": len(validation),
        "train_delay_rate": float(train[TARGET].mean()),
        "features_created": len(FEATURE_COLUMNS),
        "features_currently_modeled": len(MODEL_FEATURES),
        "excluded_currently": list(EXCLUDED),
        "log1p_features_selected_from_train_skew": list(LOG_FEATURES),
        "features": features,
        "input_sha256": {
            "manifest": file_sha256(manifest_path),
            "label_availability": file_sha256(availability_path),
            "asof_train": file_sha256(train_path),
            "validation": file_sha256(validation_path),
        },
        "test_used": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/ml/feature_audit.json")
    args = parser.parse_args()
    result = audit(args.data_dir, args.output)
    print(json.dumps({key: result[key] for key in ("train_rows", "validation_rows", "features_created", "features_currently_modeled", "test_used")}, indent=2))


if __name__ == "__main__":
    main()

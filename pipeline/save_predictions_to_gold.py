"""Synchronize label-free dashboard predictions into DuckDB Gold."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.bronze import PROJECT_ROOT


def save_to_gold(database: Path, predictions_csv: Path) -> tuple[int, int]:
    if not predictions_csv.is_file():
        raise FileNotFoundError(f"Missing {predictions_csv}; run pipeline.dashboard_prediction_export first")
    columns = ["order_id", "purchase_timestamp", "promised_delivery_days",
               "predicted_delivery_days", "delay_score", "alert_10pct_frozen_threshold",
               "risk_zone", "action", "decision_available_at", "customer_state"]
    frame = pd.read_csv(predictions_csv, usecols=columns)
    if frame.empty or frame.order_id.isna().any() or frame.order_id.duplicated().any():
        raise ValueError("Prediction export must contain unique, nonnull order IDs")
    if frame[columns[1:]].isna().any().any():
        raise ValueError("Prediction export has missing required values")
    if not frame.risk_zone.isin(["red", "yellow", "green"]).all():
        raise ValueError("Prediction export has invalid risk zones")
    frame["purchase_timestamp"] = pd.to_datetime(frame.purchase_timestamp, errors="raise")
    frame["decision_available_at"] = pd.to_datetime(frame.decision_available_at, errors="raise")
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database))
    try:
        connection.register("prediction_source", frame)
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute("CREATE SCHEMA IF NOT EXISTS gold")
            connection.execute("""
                CREATE OR REPLACE TABLE gold.fact_delivery_predictions AS
                SELECT order_id,
                       purchase_timestamp AS prediction_cutoff_ts,
                       predicted_delivery_days,
                       promised_delivery_days,
                       delay_score AS delay_risk_score,
                       alert_10pct_frozen_threshold,
                       risk_zone,
                       action AS recommended_action,
                       decision_available_at,
                       customer_state,
                       current_timestamp AS synced_at
                FROM prediction_source
            """)
            count, red_count = connection.execute("""
                SELECT count(*), count(*) FILTER (WHERE risk_zone = 'red')
                FROM gold.fact_delivery_predictions
            """).fetchone()
            if count != len(frame):
                raise ValueError("Gold row count differs from prediction export")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        return count, red_count
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/warehouse/olist.duckdb")
    parser.add_argument("--predictions", type=Path,
                        default=PROJECT_ROOT / "data/ml/models/dashboard_joint_predictions.csv")
    args = parser.parse_args()
    count, red_count = save_to_gold(args.database, args.predictions)
    print(f"Gold prediction rows: {count:,}; red orders: {red_count:,}")


if __name__ == "__main__":
    main()

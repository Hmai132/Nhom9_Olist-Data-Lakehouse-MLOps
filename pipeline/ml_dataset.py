"""Prepare leakage-audited, chronological Olist ML datasets from Gold.

This stage only creates train/validation/test data. Model fitting, imputers,
encoders and threshold selection belong to later ML stages.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import duckdb

from pipeline.bronze import PROJECT_ROOT


FEATURE_COLUMNS = (
    "feature_purchase_month",
    "feature_purchase_day_of_week",
    "feature_purchase_hour",
    "feature_customer_state",
    "feature_customer_zip_code_prefix",
    "feature_promised_delivery_days",
    "feature_item_count",
    "feature_product_count",
    "feature_seller_count",
    "feature_item_price_total",
    "feature_freight_total",
    "feature_total_weight_g",
    "feature_missing_weight_items",
    "feature_category_count",
    "feature_mean_seller_distance_km",
    "feature_sellers_missing_distance",
    "feature_same_state_seller_share",
)
TARGET_COLUMNS = (
    "target_actual_delivery_days",
    "target_is_delayed_timestamp",
    "target_is_delayed_calendar_day",
)
VALIDATION_START = datetime(2018, 5, 1)
TEST_START = datetime(2018, 7, 1)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def prepare(database: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database), read_only=True)
    try:
        available = {
            row[0] for row in connection.execute(
                "DESCRIBE SELECT * FROM gold.ml_wide_delivery_table"
            ).fetchall()
        }
        required = {"order_id", "prediction_cutoff_ts", "is_label_eligible"}
        required.update(FEATURE_COLUMNS)
        required.update(TARGET_COLUMNS)
        missing = required - available
        if missing:
            raise ValueError(f"Gold ML table is missing columns: {sorted(missing)}")

        # A strict allowlist prevents future Gold columns from silently entering X.
        selected = ["w.order_id", "w.prediction_cutoff_ts"]
        selected += [f"w.{name}" for name in FEATURE_COLUMNS]
        selected += [f"w.{name}" for name in TARGET_COLUMNS]
        base = f"""
            SELECT {', '.join(selected)},
                   f.order_delivered_customer_date AS label_available_ts
            FROM gold.ml_wide_delivery_table AS w
            JOIN gold.fact_delivery_performance AS f USING (order_id)
            WHERE w.is_label_eligible
              AND w.target_actual_delivery_days IS NOT NULL
              AND w.target_actual_delivery_days >= 0
              AND w.target_is_delayed_timestamp IS NOT NULL
              AND w.target_is_delayed_calendar_day IS NOT NULL
              AND f.order_delivered_customer_date IS NOT NULL
        """
        validation_start = sql_literal(VALIDATION_START.isoformat(sep=" "))
        test_start = sql_literal(TEST_START.isoformat(sep=" "))
        # Retain complete labeled purchase cohorts. Dropping orders according
        # to how quickly their labels arrived would favor fast deliveries.
        filters = {
            "train": f"prediction_cutoff_ts < {validation_start}",
            "validation": f"prediction_cutoff_ts >= {validation_start} AND prediction_cutoff_ts < {test_start}",
            "test": f"prediction_cutoff_ts >= {test_start}",
        }
        stats = {}
        export_columns = ["order_id", "prediction_cutoff_ts", *FEATURE_COLUMNS, *TARGET_COLUMNS]
        for split, condition in filters.items():
            query = f"SELECT {', '.join(export_columns)} FROM ({base}) WHERE {condition} ORDER BY prediction_cutoff_ts, order_id"
            path = output_dir / f"{split}.parquet"
            connection.execute(
                f"COPY ({query}) TO {sql_literal(str(path))} (FORMAT PARQUET)"
            )
            row = connection.execute(
                f"SELECT count(*), min(prediction_cutoff_ts), max(prediction_cutoff_ts), "
                f"sum(target_is_delayed_timestamp::integer), "
                f"sum(target_is_delayed_calendar_day::integer) "
                f"FROM ({query})"
            ).fetchone()
            exported = connection.read_parquet(str(path))
            exported_rows, unique_orders = exported.aggregate(
                "count(*), count(distinct order_id)"
            ).fetchone()
            if exported.columns != export_columns or exported_rows != row[0] or unique_orders != row[0]:
                raise ValueError(f"Export verification failed for {split}")
            stats[split] = {
                "rows": row[0],
                "first_purchase": row[1].isoformat() if row[1] else None,
                "last_purchase": row[2].isoformat() if row[2] else None,
                "late_timestamp": row[3],
                "late_calendar_day": row[4],
                "file": path.name,
            }
            if split != "test":
                next_start = validation_start if split == "train" else test_start
                stats[split]["labels_available_after_next_split_start"] = connection.execute(
                    f"SELECT count(*) FROM ({base}) WHERE {condition} "
                    f"AND label_available_ts >= {next_start}"
                ).fetchone()[0]
        eligible_count = connection.execute(
            f"SELECT count(*) FROM ({base})"
        ).fetchone()[0]
        if eligible_count != sum(x["rows"] for x in stats.values()):
            raise ValueError("Split row counts do not reconcile to eligible Gold rows")
        manifest = {
            "source": "gold.ml_wide_delivery_table + gold.fact_delivery_performance",
            "prediction_cutoff": "order purchase timestamp",
            "validation_start": VALIDATION_START.isoformat(),
            "test_start": TEST_START.isoformat(),
            "feature_columns": list(FEATURE_COLUMNS),
            "target_columns": list(TARGET_COLUMNS),
            "feature_availability_assumptions": {
                "feature_promised_delivery_days": "Estimated delivery date is available when the order is placed, as confirmed by the project owner."
            },
            "excluded_post_purchase_fields": ["approval", "carrier delivery", "customer delivery", "review", "order status"],
            "eligible_labeled_rows": eligible_count,
            "evaluation_scope": "retrospective purchase-time cohorts; not a historical deployment replay",
            "label_availability_caveat": "Some cohort labels arrived after the next split began; see split diagnostics. A deployment replay needs a separate label maturity design before model fitting.",
            "splits": stats,
            "preprocessing": "none; fit imputers/encoders/scalers on train only in the next stage",
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return manifest
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/warehouse/olist.duckdb")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    args = parser.parse_args()
    print(json.dumps(prepare(args.database, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

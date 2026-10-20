"""Build an as-of training cohort for the May 2018 validation period.

This stage prepares data and diagnostics only. It does not fit a model or
change the retrospective validation/test cohorts.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import duckdb

from pipeline.bronze import PROJECT_ROOT
from pipeline.ml_dataset import FEATURE_COLUMNS, TARGET_COLUMNS, VALIDATION_START, sql_literal


GAP_DAYS = 90
DIAGNOSTIC_GAPS = (0, 30, 60, 90, 120, 180, 210)


def prepare(database: Path, data_dir: Path, gap_days: int = GAP_DAYS) -> dict:
    if gap_days < 0:
        raise ValueError("Maturity gap must not be negative")
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["feature_columns"] != list(FEATURE_COLUMNS):
        raise ValueError("Prepared features differ from the current feature contract")
    if manifest["target_columns"] != list(TARGET_COLUMNS):
        raise ValueError("Prepared targets differ from the current target contract")
    if manifest["validation_start"] != VALIDATION_START.isoformat():
        raise ValueError("Validation start differs from the prepared data")

    train_path = data_dir / "train.parquet"
    validation_path = data_dir / "validation.parquet"
    output_path = data_dir / "train_asof_validation.parquet"
    report_path = data_dir / "label_availability.json"
    cutoff = sql_literal(VALIDATION_START.isoformat(sep=" "))
    columns = ["order_id", "prediction_cutoff_ts", *FEATURE_COLUMNS, *TARGET_COLUMNS]

    connection = duckdb.connect(str(database), read_only=True)
    try:
        train = f"read_parquet({sql_literal(str(train_path))})"
        validation = f"read_parquet({sql_literal(str(validation_path))})"
        base = f"""
            SELECT t.*, f.order_delivered_customer_date AS label_available_ts
            FROM {train} AS t
            JOIN gold.fact_delivery_performance AS f USING (order_id)
        """
        train_rows, unique_orders, anomalous_label_times = connection.execute(
            f"SELECT count(*), count(distinct order_id), "
            f"count(*) FILTER (WHERE label_available_ts < prediction_cutoff_ts) "
            f"FROM ({base})"
        ).fetchone()
        if train_rows != manifest["splits"]["train"]["rows"] or unique_orders != train_rows:
            raise ValueError("Training rows do not reconcile with the manifest")
        if anomalous_label_times:
            raise ValueError("Delivery labels earlier than purchase time found")

        diagnostics = []
        for days in sorted(set((*DIAGNOSTIC_GAPS, gap_days))):
            purchase_end = sql_literal((VALIDATION_START - timedelta(days=days)).isoformat(sep=" "))
            eligible, known, known_late, future_late = connection.execute(
                f"SELECT count(*), "
                f"count(*) FILTER (WHERE label_available_ts < {cutoff}), "
                f"count(*) FILTER (WHERE label_available_ts < {cutoff} "
                f"AND target_is_delayed_calendar_day), "
                f"count(*) FILTER (WHERE label_available_ts >= {cutoff} "
                f"AND target_is_delayed_calendar_day) "
                f"FROM ({base}) WHERE prediction_cutoff_ts < {purchase_end}"
            ).fetchone()
            diagnostics.append({
                "maturity_days": days,
                "eligible_labeled_orders_retrospective": eligible,
                "labels_known_at_cutoff": known,
                "labels_arriving_later": eligible - known,
                "known_label_fraction": known / eligible if eligible else None,
                "known_calendar_day_late": known_late,
                "later_calendar_day_late": future_late,
                "known_late_rate": known_late / known if known else None,
            })

        purchase_end = sql_literal((VALIDATION_START - timedelta(days=gap_days)).isoformat(sep=" "))
        query = (
            f"SELECT {', '.join(columns)} FROM ({base}) "
            f"WHERE prediction_cutoff_ts < {purchase_end} "
            f"AND label_available_ts < {cutoff} "
            f"ORDER BY prediction_cutoff_ts, order_id"
        )
        connection.execute(f"COPY ({query}) TO {sql_literal(str(output_path))} (FORMAT PARQUET)")
        exported = connection.read_parquet(str(output_path))
        exported_rows, exported_unique, latest_purchase = exported.aggregate(
            "count(*), count(distinct order_id), max(prediction_cutoff_ts)"
        ).fetchone()
        if exported.columns != columns or exported_rows != exported_unique:
            raise ValueError("As-of training export failed verification")
        selected = next(item for item in diagnostics if item["maturity_days"] == gap_days)
        if exported_rows != selected["labels_known_at_cutoff"]:
            raise ValueError("As-of training count disagrees with diagnostics")
        validation_rows = connection.execute(f"SELECT count(*) FROM {validation}").fetchone()[0]
        if validation_rows != manifest["splits"]["validation"]["rows"]:
            raise ValueError("Validation rows changed after preparation")

        report = {
            "evaluation_design": "historical as-of training at validation start",
            "validation_start": VALIDATION_START.isoformat(),
            "maturity_gap_days": gap_days,
            "train_purchase_before": (VALIDATION_START - timedelta(days=gap_days)).isoformat(),
            "train_label_available_before": VALIDATION_START.isoformat(),
            "label_available_proxy": "order_delivered_customer_date; conservative for the delay label",
            "target_for_delay": "target_is_delayed_calendar_day",
            "feature_columns": list(FEATURE_COLUMNS),
            "target_columns": list(TARGET_COLUMNS),
            "train_rows_retrospective": train_rows,
            "train_rows_asof": exported_rows,
            "latest_asof_train_purchase": latest_purchase.isoformat() if latest_purchase else None,
            "validation_rows_unchanged": validation_rows,
            "diagnostics": diagnostics,
            "limitations": [
                "Gold is a static historical extract; feature values are not versioned as of each purchase.",
                "Maturity gaps reduce recent training data; remaining unknown labels can still bias the observed cohort.",
                "The diagnostic denominator contains only orders eventually eligible for a delivery label.",
                "No model performance is established by preparing this cohort."
            ],
            "files": {"asof_train": output_path.name, "validation": validation_path.name},
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data/warehouse/olist.duckdb")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--gap-days", type=int, default=GAP_DAYS)
    args = parser.parse_args()
    print(json.dumps(prepare(args.database, args.data_dir, args.gap_days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

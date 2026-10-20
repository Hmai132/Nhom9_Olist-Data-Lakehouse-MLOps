"""Simulate risk bands and configurable manual-call capacity by shift.

The scorer has already run. Decisions use order time, order ID and frozen model
score only; true delay labels are joined afterward for descriptive evaluation.
This is a post-test operational scenario, not a new unbiased model test.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.bronze import PROJECT_ROOT
from pipeline.regression_baseline import file_sha256


def validate_config(config: dict) -> None:
    expected = {"shift_hours", "red_fraction", "yellow_cumulative_fraction",
                "default_manual_capacity_per_shift", "shift_capacity_overrides"}
    if set(config) != expected:
        raise ValueError(f"Policy config must contain exactly {sorted(expected)}")
    hours = config["shift_hours"]
    if type(hours) is not int or hours < 1 or 24 % hours:
        raise ValueError("shift_hours must be a positive divisor of 24")
    red = config["red_fraction"]
    yellow = config["yellow_cumulative_fraction"]
    if not (0 < red < yellow <= 1):
        raise ValueError("Expected 0 < red_fraction < yellow_cumulative_fraction <= 1")
    default = config["default_manual_capacity_per_shift"]
    if type(default) is not int or default < 0:
        raise ValueError("Manual capacity must be a nonnegative integer")
    overrides = config["shift_capacity_overrides"]
    if not isinstance(overrides, dict):
        raise ValueError("shift_capacity_overrides must be an object")
    for key, capacity in overrides.items():
        try:
            shift_start = pd.Timestamp(key)
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid shift timestamp: {key}") from error
        if shift_start.tz is not None or shift_start != shift_start.floor(f"{hours}h"):
            raise ValueError(f"Override key is not a naive, aligned shift start: {key}")
        if type(capacity) is not int or capacity < 0:
            raise ValueError(f"Invalid manual capacity for shift {key}")


def assign_actions(orders: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Return one deterministic decision per order using only purchase-time data."""
    validate_config(config)
    required = {"order_id", "prediction_cutoff_ts", "delay_score"}
    if required - set(orders):
        raise ValueError(f"Missing policy inputs: {sorted(required - set(orders))}")
    if "actual_is_delayed_calendar_day" in orders:
        raise ValueError("Labels must not enter the policy decision function")
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError("Missing or duplicate order IDs")
    if not np.isfinite(orders.delay_score.to_numpy(dtype=float)).all():
        raise ValueError("Risk scores must be finite")
    if ((orders.delay_score < 0) | (orders.delay_score > 1)).any():
        raise ValueError("Risk scores must lie in [0, 1]")
    decisions = orders.loc[:, ["order_id", "prediction_cutoff_ts", "delay_score"]].copy()
    decisions["prediction_cutoff_ts"] = pd.to_datetime(decisions.prediction_cutoff_ts)
    if decisions.prediction_cutoff_ts.isna().any() or decisions.prediction_cutoff_ts.dt.tz is not None:
        raise ValueError("Policy requires nonmissing, timezone-naive order timestamps")
    hours = config["shift_hours"]
    decisions["shift_start"] = decisions.prediction_cutoff_ts.dt.floor(f"{hours}h")
    decisions = decisions.sort_values(
        ["shift_start", "delay_score", "order_id"],
        ascending=[True, False, True], kind="mergesort",
    ).reset_index(drop=True)
    groups = decisions.groupby("shift_start", sort=False)
    decisions["shift_orders"] = groups.order_id.transform("size")
    decisions["risk_rank_in_shift"] = groups.cumcount() + 1
    red_count = np.floor(decisions.shift_orders * config["red_fraction"]).astype(int)
    yellow_end = np.floor(decisions.shift_orders * config["yellow_cumulative_fraction"]).astype(int)
    decisions["risk_zone"] = np.select(
        [decisions.risk_rank_in_shift <= red_count,
         decisions.risk_rank_in_shift <= yellow_end],
        ["red", "yellow"], default="green",
    )
    capacity = decisions.shift_start.dt.strftime("%Y-%m-%dT%H:%M:%S").map(
        config["shift_capacity_overrides"]
    ).fillna(config["default_manual_capacity_per_shift"]).astype(int)
    decisions["manual_capacity_for_shift"] = capacity
    manual = (decisions.risk_zone == "red") & (decisions.risk_rank_in_shift <= capacity)
    automatic = decisions.risk_zone.isin(["red", "yellow"]) & ~manual
    decisions["action"] = np.select(
        [manual, automatic], ["manual_call", "automated_message"], default="none"
    )
    decisions["decision_available_at"] = decisions.shift_start + pd.Timedelta(hours=hours)
    return decisions.sort_values(["prediction_cutoff_ts", "order_id"]).reset_index(drop=True)


def simulate(predictions_path: Path, test_metrics_path: Path, config_path: Path,
             output_dir: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_config(config)
    test_metrics = json.loads(test_metrics_path.read_text(encoding="utf-8"))
    if not test_metrics["test_used"] or test_metrics["model_refit_on_test"] or test_metrics["threshold_tuned_on_test"]:
        raise ValueError("Expected the frozen one-time test before a policy scenario")
    if test_metrics["files"]["test_predictions"] != predictions_path.name:
        raise ValueError("Policy prediction file differs from frozen test result")
    drift_path = predictions_path.parent / "historical_test_drift_audit.json"
    if drift_path.exists():
        drift = json.loads(drift_path.read_text(encoding="utf-8"))
        if drift["input_sha256"]["test_predictions"] != file_sha256(predictions_path):
            raise ValueError("Frozen test predictions changed since drift diagnosis")
    predictions = pd.read_csv(predictions_path, parse_dates=["prediction_cutoff_ts"])
    if len(predictions) != test_metrics["test_rows"]:
        raise ValueError("Policy source row count differs from frozen test result")
    if not predictions.actual_is_delayed_calendar_day.isin([0, 1]).all():
        raise ValueError("Invalid retrospective test labels")

    # This projection is the full decision input; labels are joined only after.
    decisions = assign_actions(
        predictions.loc[:, ["order_id", "prediction_cutoff_ts", "delay_score"]], config
    )
    evaluated = decisions.merge(
        predictions.loc[:, ["order_id", "actual_is_delayed_calendar_day"]],
        on="order_id", how="left", validate="one_to_one",
    )
    if len(evaluated) != len(predictions) or evaluated.actual_is_delayed_calendar_day.isna().any():
        raise ValueError("Policy decisions did not reconcile to retrospective labels")
    counts = evaluated.groupby("action").agg(
        orders=("order_id", "size"), observed_late=("actual_is_delayed_calendar_day", "sum")
    )
    action_metrics = {
        action: {"orders": int(row.orders), "observed_late": int(row.observed_late),
                 "observed_late_fraction": float(row.observed_late / row.orders)}
        for action, row in counts.iterrows()
    }
    workload = evaluated.groupby("shift_start").agg(
        shift_orders=("order_id", "size"),
        capacity=("manual_capacity_for_shift", "first"),
        manual_calls=("action", lambda value: int((value == "manual_call").sum())),
        red_orders=("risk_zone", lambda value: int((value == "red").sum())),
    )
    if (workload.manual_calls > workload.capacity).any():
        raise ValueError("A shift exceeded its configured manual capacity")
    if (workload.manual_calls > workload.red_orders).any():
        raise ValueError("Manual calls exceeded red candidates")
    if len(decisions) != len(predictions):
        raise ValueError("A policy decision was lost")
    result = {
        "scenario": "post-test exploratory operational simulation; no causal intervention effect",
        "config": config,
        "test_orders": len(predictions),
        "shifts": len(workload),
        "risk_zone_counts": {str(k): int(v) for k, v in evaluated.risk_zone.value_counts().items()},
        "action_metrics": action_metrics,
        "manual_calls_total": int(workload.manual_calls.sum()),
        "manual_calls_max_single_shift": int(workload.manual_calls.max()),
        "shifts_with_red_overflow": int((workload.red_orders > workload.manual_calls).sum()),
        "shifts_at_manual_capacity": int((workload.manual_calls == workload.capacity).sum()),
        "capacity_violations": 0,
        "outcome_interpretation": "Observed late counts describe ranking only; this historical data cannot estimate how calls or messages would change delivery outcomes.",
        "timing_limit": "Batch ranking completes at shift close, not immediately when each order is placed.",
        "validation_limit": "Policy fractions and quota were specified after the test was opened; these are exploratory test-cohort descriptions, not a fresh unbiased evaluation.",
        "source_sha256": {
            "frozen_test_metrics": file_sha256(test_metrics_path),
            "frozen_test_predictions": file_sha256(predictions_path),
            "policy_config": file_sha256(config_path),
        },
        "files": {"decisions": "hybrid_policy_test_exploratory_decisions.csv"},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluated.to_csv(output_dir / result["files"]["decisions"], index=False)
    (output_dir / "hybrid_policy_test_exploratory_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path,
                        default=PROJECT_ROOT / "data/ml/models/historical_test_predictions.csv")
    parser.add_argument("--test-metrics", type=Path,
                        default=PROJECT_ROOT / "data/ml/models/historical_test_metrics.json")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "pipeline/alert_policy.json")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    result = simulate(args.predictions, args.test_metrics, args.config, args.output_dir)
    print(json.dumps({key: result[key] for key in (
        "test_orders", "shifts", "risk_zone_counts", "action_metrics",
        "manual_calls_total", "shifts_with_red_overflow", "capacity_violations",
    )}, indent=2))


if __name__ == "__main__":
    main()

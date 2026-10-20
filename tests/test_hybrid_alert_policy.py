"""Contract checks for shift ranking and manual-call limits."""

import unittest

import pandas as pd

from pipeline.hybrid_alert_policy import assign_actions


class HybridAlertPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            "shift_hours": 8,
            "red_fraction": 0.05,
            "yellow_cumulative_fraction": 0.25,
            "default_manual_capacity_per_shift": 2,
            "shift_capacity_overrides": {},
        }

    def test_red_overflow_becomes_automatic_and_green_is_ignored(self) -> None:
        orders = pd.DataFrame({
            "order_id": [f"order_{i:03}" for i in range(100)],
            "prediction_cutoff_ts": ["2018-07-01 09:00:00"] * 100,
            "delay_score": [1 - i / 100 for i in range(100)],
        })
        decisions = assign_actions(orders, self.config)
        self.assertEqual(decisions.risk_zone.value_counts().to_dict(),
                         {"green": 75, "yellow": 20, "red": 5})
        self.assertEqual(decisions.action.value_counts().to_dict(),
                         {"none": 75, "automated_message": 23, "manual_call": 2})
        self.assertEqual(set(decisions.loc[decisions.action == "manual_call", "order_id"]),
                         {"order_000", "order_001"})
        self.assertTrue((decisions.decision_available_at == pd.Timestamp("2018-07-01 16:00:00")).all())

    def test_shift_override_and_tie_break_are_deterministic(self) -> None:
        config = {**self.config, "red_fraction": 0.5, "yellow_cumulative_fraction": 1.0,
                  "shift_capacity_overrides": {"2018-07-01T16:00:00": 0}}
        orders = pd.DataFrame({
            "order_id": ["b", "a", "d", "c"],
            "prediction_cutoff_ts": ["2018-07-01 08:00:00", "2018-07-01 08:00:00",
                                     "2018-07-01 16:00:00", "2018-07-01 16:00:00"],
            "delay_score": [0.8, 0.8, 0.9, 0.9],
        })
        decisions = assign_actions(orders, config).set_index("order_id")
        self.assertEqual(decisions.loc["a", "action"], "manual_call")
        self.assertEqual(decisions.loc["b", "action"], "automated_message")
        self.assertEqual(decisions.loc["c", "risk_zone"], "red")
        self.assertEqual(decisions.loc["c", "action"], "automated_message")
        self.assertEqual(decisions.loc["d", "action"], "automated_message")

    def test_labels_cannot_enter_decision_function(self) -> None:
        orders = pd.DataFrame({
            "order_id": ["a"], "prediction_cutoff_ts": ["2018-07-01 08:00:00"],
            "delay_score": [0.8], "actual_is_delayed_calendar_day": [1],
        })
        with self.assertRaises(ValueError):
            assign_actions(orders, self.config)


if __name__ == "__main__":
    unittest.main()

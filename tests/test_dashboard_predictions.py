import unittest

import duckdb

from dashboard.server import DEFAULT_DATABASE, PREDICTION_METADATA, prediction_data


@unittest.skipUnless(DEFAULT_DATABASE.exists() and PREDICTION_METADATA.exists(),
                     "Gold predictions are unavailable")
class PredictionDashboardTests(unittest.TestCase):
    def test_both_predictions_use_same_test_cohort_without_labels(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            data = prediction_data(connection, {})
            columns = [row[0] for row in connection.execute(
                "describe select * from gold.fact_delivery_predictions"
            ).fetchall()]
        self.assertEqual(data["summary"]["orders"], data["metadata"]["rows"])
        self.assertEqual(data["summary"]["orders"], 12507)
        self.assertEqual(data["summary"]["invalid_regression_outputs"], 2)
        self.assertEqual(data["summary"]["frozen_alerts"], 5116)
        self.assertEqual(data["summary"]["manual_calls"], 538)
        self.assertEqual(data["summary"]["automated_messages"], 2519)
        self.assertEqual(data["summary"]["monitor_only"], 9450)
        self.assertEqual(sum(data["summary"][key] for key in
                             ("manual_calls", "automated_messages", "monitor_only")), 12507)
        self.assertTrue({"predicted_delivery_days", "delay_risk_score", "alert_10pct_frozen_threshold"} <= set(columns))
        self.assertFalse(any(name in columns for name in ("actual_delivery_days", "is_delayed", "target_delivery_days")))
        self.assertNotIn("actual_is_delayed_calendar_day", columns)
        self.assertTrue({"risk_zone", "recommended_action", "decision_available_at"} <= set(columns))
        self.assertTrue(data["metadata"]["regression_display_only_on_test"])
        self.assertFalse(data["metadata"]["regression_test_metrics_computed"])
        self.assertFalse(data["metadata"]["score_is_calibrated_probability"])

    def test_month_and_order_filters(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            all_data = prediction_data(connection, {})
            july = prediction_data(connection, {"month": ["201807"]})
            august = prediction_data(connection, {"month": ["201808"]})
            first_id = all_data["orders"][0]["order_id"]
            one = prediction_data(connection, {"order_id": [first_id]})
        self.assertEqual(july["summary"]["orders"] + august["summary"]["orders"], all_data["summary"]["orders"])
        self.assertEqual(one["summary"]["orders"], 1)
        self.assertEqual(one["orders"][0]["order_id"], first_id)
        self.assertIsInstance(one["orders"][0]["purchase_timestamp"], str)

    def test_invalid_order_id_is_rejected(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            with self.assertRaises(ValueError):
                prediction_data(connection, {"order_id": ["not-an-order-id"]})
            with self.assertRaises(ValueError):
                prediction_data(connection, {"action": ["unknown"]})

    def test_manager_queue_filters_actions_without_changing_summary(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            all_data = prediction_data(connection, {})
            calls = prediction_data(connection, {"action": ["manual_call"]})
        self.assertEqual(calls["summary"], all_data["summary"])
        self.assertTrue(all(row["action"] == "manual_call" for row in calls["orders"]))
        self.assertEqual(sum(row["orders"] for row in calls["weekly"]), calls["summary"]["orders"])


if __name__ == "__main__":
    unittest.main()

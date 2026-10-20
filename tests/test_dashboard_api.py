import unittest

import duckdb

from dashboard.server import (
    DEFAULT_DATABASE, dashboard_data, month_bounds, options, parse_filters, shift_month,
)


@unittest.skipUnless(DEFAULT_DATABASE.exists(), "Gold DuckDB database is unavailable")
class DashboardApiTests(unittest.TestCase):
    def test_selected_month_and_mom_reconcile_to_fact(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            valid = options(connection)
            filters = parse_filters({}, valid)
            data = dashboard_data(connection, filters, valid)
            month = valid["default_month"]
            start, end = month_bounds(month)
            prior_start, prior_end = month_bounds(shift_month(month, -1))
            expected = connection.execute("""
                select count(*),
                       count(*) filter (where is_delivery_label_eligible),
                       count(*) filter (where is_delayed_calendar_day),
                       sum(item_price_total),
                       sum(actual_delivery_days) filter (where is_delivery_label_eligible),
                       count(review_score_mean),
                       sum(review_score_mean)
                from gold.fact_delivery_performance
                where purchase_date_key between ? and ?
            """, [start, end]).fetchone()
            previous = connection.execute("""
                select count(*),
                       count(*) filter (where is_delivery_label_eligible),
                       count(*) filter (where is_delayed_calendar_day)
                from gold.fact_delivery_performance
                where purchase_date_key between ? and ?
            """, [prior_start, prior_end]).fetchone()
            expected_stages = connection.execute("""
                select count(*) filter (where is_delivery_label_eligible),
                       count(seller_preparation_days) filter (where is_delivery_label_eligible),
                       avg(seller_preparation_days) filter (where is_delivery_label_eligible)
                from gold.fact_delivery_performance
                where purchase_date_key between ? and ?
            """, [start, end]).fetchone()
            category_total = connection.execute("""
                select sum(ordered_item_value) from gold.dashboard_category_daily
                where purchase_date_key between ? and ?
            """, [start, end]).fetchone()[0]
        current = data["comparison"]["current"]
        self.assertEqual((current["orders"], current["eligible_orders"], current["late_orders"]), expected[:3])
        self.assertAlmostEqual(float(current["ordered_item_value"]), float(expected[3]), places=2)
        self.assertAlmostEqual(data["comparison"]["current_delivery_days"], float(expected[4])/expected[1])
        self.assertEqual(current["reviewed_orders"], expected[5])
        self.assertAlmostEqual(float(current["review_score_sum"]), float(expected[6]))
        self.assertAlmostEqual(data["comparison"]["current_aov"], float(expected[3])/expected[0])
        self.assertAlmostEqual(data["comparison"]["current_review_score"], float(expected[6])/expected[5])
        self.assertEqual(data["comparison"]["previous"]["orders"], previous[0])
        self.assertAlmostEqual(data["comparison"]["mom"]["orders_percent"], (expected[0]/previous[0]-1)*100)
        self.assertAlmostEqual(data["comparison"]["mom"]["late_orders_percent"], (expected[2]/previous[2]-1)*100)
        self.assertAlmostEqual(data["comparison"]["mom"]["late_rate_percentage_points"],
                               (expected[2]/expected[1]-previous[2]/previous[1])*100)
        self.assertAlmostEqual(float(category_total), float(expected[3]), places=2)
        self.assertAlmostEqual(sum(float(row["ordered_item_value"]) for row in data["categories"]),
                               float(category_total), places=2)
        self.assertAlmostEqual(sum(float(row["ordered_item_value"]) for row in data["seller_states"]),
                               float(category_total), places=2)
        self.assertEqual(sum(row["item_lines"] for row in data["categories"]),
                         data["product_summary"]["item_lines"])
        self.assertEqual(sum(row["active_sellers"] for row in data["seller_states"]),
                         data["product_summary"]["active_sellers"])
        for rows in data["breakdowns"].values():
            self.assertEqual(sum(row["orders"] for row in rows), current["orders"])
        self.assertEqual(sum(row["orders"] for row in data["overview_states"]), current["orders"])
        self.assertEqual(sum(row["previous_orders"] for row in data["overview_states"]), previous[0])
        self.assertEqual(sum(row["eligible_orders"] for row in data["overview_states"]), expected[1])
        self.assertEqual(sum(row["previous_late_orders"] for row in data["overview_states"]), previous[2])
        stages = {row["delivery_group"]: row for row in data["delivery_stages"]}
        self.assertEqual(stages["all"]["eligible_orders"], expected_stages[0])
        self.assertEqual(stages["all"]["preparation_count"], expected_stages[1])
        self.assertAlmostEqual(stages["all"]["preparation_days"], expected_stages[2])
        self.assertEqual(stages["late"]["eligible_orders"], current["late_orders"])
        for cells in data["delivery_matrix"].values():
            self.assertEqual(sum(row["eligible_orders"] for row in cells), current["eligible_orders"])
            self.assertEqual(sum(row["late_orders"] for row in cells), current["late_orders"])

    def test_filters_apply_to_all_views(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            valid = options(connection)
            filters = parse_filters({"month": ["2018-01"], "state": ["SP"], "status": ["delivered"]}, valid)
            data = dashboard_data(connection, filters, valid)
            expected_orders = connection.execute("""
                select sum(order_count) from gold.dashboard_order_daily
                where purchase_date_key between 20180101 and 20180131
                  and customer_state = 'SP' and order_status = 'delivered'
            """).fetchone()[0]
            expected_top_category = connection.execute("""
                select category_name from gold.dashboard_category_daily
                where purchase_date_key between 20180101 and 20180131
                  and customer_state = 'SP' and order_status = 'delivered'
                group by 1 order by sum(ordered_item_value) desc, category_name limit 1
            """).fetchone()[0]
            expected_seller_totals = connection.execute("""
                select sum(order_item_count), sum(ordered_item_value),
                       count(distinct seller_key)
                from gold.dashboard_seller_daily
                where purchase_date_key between 20180101 and 20180131
                  and customer_state = 'SP' and order_status = 'delivered'
            """).fetchone()
        self.assertEqual(data["comparison"]["current"]["orders"], expected_orders)
        self.assertEqual(data["categories"][0]["category_name"], expected_top_category)
        self.assertEqual(data["product_summary"]["item_lines"], expected_seller_totals[0])
        self.assertEqual(data["product_summary"]["active_sellers"], expected_seller_totals[2])
        self.assertAlmostEqual(sum(float(row["ordered_item_value"]) for row in data["seller_states"]),
                               float(expected_seller_totals[1]), places=2)
        self.assertEqual(data["breakdowns"]["customer_state"][0]["label"], "SP")
        self.assertEqual([row["label"] for row in data["overview_states"]], ["SP"])
        self.assertEqual({row["label"] for row in data["delivery_matrix"]["customer_state"]}, {"SP"})
        self.assertEqual(data["breakdowns"]["order_status"][0]["label"], "delivered")
        self.assertEqual(data["trend"][-1]["month_key"], 201801)
        self.assertEqual([row["label"] for row in data["customer"]["breakdowns"]["customer_state"]], ["SP"])
        self.assertEqual(data["customer"]["trend"][-1]["month_key"], 201801)
        self.assertEqual(data["customer"]["comparison"]["current"]["orders"], expected_orders)

    def test_partial_month_and_invalid_filters(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            valid = options(connection)
            latest = valid["months"][-1]
            data = dashboard_data(connection, parse_filters({"month": [str(latest)]}, valid), valid)
        self.assertEqual(data["comparison"]["month"], latest)
        self.assertTrue(data["comparison"]["month_is_partial"])
        self.assertEqual(shift_month(201801, -1), 201712)
        for raw in ({"month": ["abc"]}, {"month": ["209901"]}, {"state": ["INVALID"]},
                    {"status": ["INVALID"]}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_filters(raw, valid)

    def test_no_eligible_deliveries_does_not_invent_a_late_rate(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            valid = options(connection)
            data = dashboard_data(connection,
                                  parse_filters({"month": ["201808"], "status": ["canceled"]}, valid), valid)
        self.assertEqual(data["comparison"]["current"]["eligible_orders"], 0)
        self.assertIsNone(data["comparison"]["current_late_rate"])
        self.assertIsNone(data["customer"]["comparison"]["current_rates"]["review_coverage"])
        self.assertEqual(data["delivery_stages"][0]["eligible_orders"], 0)
        self.assertEqual(sum(row["eligible_orders"] for row in data["delivery_matrix"]["customer_state"]), 0)

    def test_customer_identity_and_review_denominators(self):
        with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as connection:
            valid = options(connection)
            month = valid["default_month"]
            start, end = month_bounds(month)
            data = dashboard_data(connection, parse_filters({}, valid), valid)
            expected = connection.execute("""
                select count(distinct customer_key), count(review_score_mean),
                       count(*) filter (where review_score_mean <= 2),
                       count(*) filter (where order_status = 'delivered'),
                       count(*) filter (where order_status = 'delivered' and review_score_mean is not null)
                from gold.fact_delivery_performance
                where purchase_date_key between ? and ?
            """, [start, end]).fetchone()
            first_seen = connection.execute("""
                select count(distinct customer_key)
                from gold.dashboard_customer_order_base
                where purchase_date_key between ? and ?
                  and first_observed_purchase_date_key < ?
            """, [start, end, start]).fetchone()[0]
        customer = data["customer"]
        current = customer["comparison"]["current"]
        rates = customer["comparison"]["current_rates"]
        self.assertEqual((current["buyers"], current["reviewed_orders"],
                          current["low_review_orders"], current["delivered_orders"],
                          current["delivered_reviewed_orders"]), expected)
        self.assertEqual(current["previously_observed_buyers"], first_seen)
        self.assertAlmostEqual(rates["review_coverage"], expected[4] / expected[3])
        self.assertAlmostEqual(rates["low_review_share"], expected[2] / expected[1])
        self.assertEqual(sum(row["orders"] for row in customer["segments"]), current["orders"])
        self.assertEqual(sum(row["reviewed_orders"] for row in customer["breakdowns"]["customer_state"]),
                         current["reviewed_orders"])
        self.assertEqual(sum(row["eligible_orders"] for row in customer["delivery_reviews"]),
                         data["comparison"]["current"]["eligible_orders"])


if __name__ == "__main__":
    unittest.main()

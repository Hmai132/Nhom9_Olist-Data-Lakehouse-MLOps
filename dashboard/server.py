"""Local, read-only Olist dashboard backed by the reconciled Gold marts."""

from __future__ import annotations

import argparse
import calendar
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data/warehouse/olist.duckdb"
PREDICTION_EXPORT = PROJECT_ROOT / "data/ml/models/dashboard_joint_predictions.csv"
PREDICTION_METADATA = PROJECT_ROOT / "data/ml/models/dashboard_joint_predictions_metadata.json"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
BREAKDOWN_DIMENSIONS = {
    "customer_state": "customer_state",
    "order_status": "order_status",
    "order_size_band": "order_size_band",
    "promise_window_band": "promise_window_band",
    "purchase_weekday": "purchase_weekday",
}
MATRIX_DIMENSIONS = ("customer_state", "order_size_band", "purchase_weekday")
EXPERIENCE_DIMENSIONS = ("customer_state", "order_size_band", "promise_window_band", "purchase_weekday")


def rows(connection: duckdb.DuckDBPyConnection, query: str, parameters: list | None = None) -> list[dict]:
    result = connection.execute(query, parameters or [])
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def options(connection: duckdb.DuckDBPyConnection) -> dict:
    bounds = rows(connection, """
        select min(purchase_date_key) as first_date_key,
               max(purchase_date_key) as last_date_key
        from gold.dashboard_order_daily
    """)[0]
    last = str(bounds["last_date_key"])
    month_stats = rows(connection, """
        select floor(purchase_date_key / 100)::integer as month_key,
               min(purchase_date_key) as first_day,
               max(purchase_date_key) as last_day,
               sum(order_count) as orders
        from gold.dashboard_order_daily group by 1 order by 1
    """)
    months = [row["month_key"] for row in month_stats]
    complete_months = [row["month_key"] for row in month_stats
                       if (row["first_day"], row["last_day"]) == month_bounds(row["month_key"])]
    default_month = complete_months[-1] if complete_months else months[-1]
    return {
        "first_date": str(bounds["first_date_key"]),
        "last_date": last,
        "months": months,
        "complete_months": complete_months,
        "default_month": default_month,
        "states": [row["customer_state"] for row in rows(
            connection, "select distinct customer_state from gold.dashboard_order_daily order by 1"
        )],
        "statuses": [row["order_status"] for row in rows(
            connection, "select distinct order_status from gold.dashboard_order_daily order by 1"
        )],
    }


def shift_month(month_key: int, offset: int) -> int:
    year, month = divmod(month_key, 100)
    absolute = year * 12 + month - 1 + offset
    new_year, zero_month = divmod(absolute, 12)
    return new_year * 100 + zero_month + 1


def month_bounds(month_key: int) -> tuple[int, int]:
    year, month = divmod(month_key, 100)
    last_day = calendar.monthrange(year, month)[1]
    return year * 10000 + month * 100 + 1, year * 10000 + month * 100 + last_day


def parse_filters(raw: dict[str, list[str]], valid: dict) -> tuple[int, str, str]:
    try:
        month = int(raw.get("month", [str(valid["default_month"])])[0].replace("-", ""))
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid comparison month") from error
    if month not in valid["months"]:
        raise ValueError("Comparison month has no Olist orders")
    state = raw.get("state", ["all"])[0]
    status = raw.get("status", ["all"])[0]
    if state != "all" and state not in valid["states"]:
        raise ValueError("Unknown customer state")
    if status != "all" and status not in valid["statuses"]:
        raise ValueError("Unknown order status")
    return month, state, status


def customer_experience_data(connection: duckdb.DuckDBPyConnection,
                             filters: tuple[int, str, str]) -> dict:
    month, state, status = filters
    start, end = month_bounds(month)
    previous_start, previous_end = month_bounds(shift_month(month, -1))
    first_trend_month = shift_month(month, -11)
    where = "purchase_date_key between ? and ? and (? = 'all' or customer_state = ?) and (? = 'all' or order_status = ?)"
    def parameters(first: int, last: int) -> list:
        return [first, last, state, state, status, status]
    def totals(first: int, last: int) -> dict:
        return rows(connection, f"""
            select count(*) as orders,
                   count(distinct customer_key) as buyers,
                   count(distinct customer_key) filter (
                       where first_observed_purchase_date_key < ?
                   ) as previously_observed_buyers,
                   count(*) filter (where observed_order_number > 1) as subsequent_orders,
                   count(*) filter (where order_status = 'delivered') as delivered_orders,
                   count(*) filter (
                       where order_status = 'delivered' and review_score_mean is not null
                   ) as delivered_reviewed_orders,
                   count(review_score_mean) as reviewed_orders,
                   coalesce(sum(review_score_mean), 0) as review_score_sum,
                   count(*) filter (where review_score_mean <= 2) as low_review_orders
            from gold.dashboard_customer_order_base where {where}
        """, [first, *parameters(first, last)])[0]
    current, previous = totals(start, end), totals(previous_start, previous_end)
    def ratio(total: dict, numerator: str, denominator: str) -> float | None:
        return total[numerator] / total[denominator] if total[denominator] else None
    def mean(total: dict) -> float | None:
        return float(total["review_score_sum"]) / total["reviewed_orders"] if total["reviewed_orders"] else None
    def percent_change(numerator: str) -> float | None:
        return (current[numerator] / previous[numerator] - 1) * 100 if previous[numerator] else None
    current_rates = {
        "returning_buyer_share": ratio(current, "previously_observed_buyers", "buyers"),
        "review_coverage": ratio(current, "delivered_reviewed_orders", "delivered_orders"),
        "low_review_share": ratio(current, "low_review_orders", "reviewed_orders"),
        "review_score": mean(current),
    }
    previous_rates = {
        "returning_buyer_share": ratio(previous, "previously_observed_buyers", "buyers"),
        "review_coverage": ratio(previous, "delivered_reviewed_orders", "delivered_orders"),
        "low_review_share": ratio(previous, "low_review_orders", "reviewed_orders"),
        "review_score": mean(previous),
    }
    changes = {
        "buyers_percent": percent_change("buyers"),
        "previously_observed_buyers_percent": percent_change("previously_observed_buyers"),
    }
    for name in current_rates:
        now, before = current_rates[name], previous_rates[name]
        changes[name + "_difference"] = (now - before) * (1 if name == "review_score" else 100) if now is not None and before is not None else None
    trend = rows(connection, """
        select floor(purchase_date_key / 100)::integer as month_key,
               count(distinct customer_key) as buyers,
               count(distinct customer_key) filter (
                   where first_observed_purchase_date_key < floor(purchase_date_key / 100)::integer * 100 + 1
               ) as previously_observed_buyers,
               count(review_score_mean) as reviewed_orders,
               coalesce(sum(review_score_mean), 0) as review_score_sum,
               count(*) filter (where review_score_mean <= 2) as low_review_orders
        from gold.dashboard_customer_order_base
        where floor(purchase_date_key / 100)::integer between ? and ?
          and (? = 'all' or customer_state = ?)
          and (? = 'all' or order_status = ?)
        group by 1 order by 1
    """, [first_trend_month, month, state, state, status, status])
    segments = rows(connection, f"""
        select case when observed_order_number = 1 then 'first' else 'subsequent' end as segment,
               count(*) as orders, count(distinct customer_key) as buyers,
               sum(item_price_total) as ordered_item_value,
               count(*) filter (where is_delivery_label_eligible) as eligible_orders,
               count(*) filter (where is_delayed_calendar_day) as late_orders,
               count(review_score_mean) as reviewed_orders,
               coalesce(sum(review_score_mean), 0) as review_score_sum,
               count(*) filter (where review_score_mean <= 2) as low_review_orders
        from gold.dashboard_customer_order_base where {where}
        group by 1 order by 1
    """, parameters(start, end))
    delivery_reviews = rows(connection, f"""
        select case when is_delayed_calendar_day then 'late' else 'on_time' end as delivery_group,
               count(*) as eligible_orders,
               count(review_score_mean) as reviewed_orders,
               coalesce(sum(review_score_mean), 0) as review_score_sum,
               count(*) filter (where review_score_mean <= 2) as low_review_orders
        from gold.dashboard_customer_order_base
        where {where} and is_delivery_label_eligible
        group by 1 order by 1
    """, parameters(start, end))
    breakdowns = {}
    for dimension in EXPERIENCE_DIMENSIONS:
        breakdowns[dimension] = rows(connection, f"""
            select {dimension} as label, count(*) as orders,
                   count(review_score_mean) as reviewed_orders,
                   coalesce(sum(review_score_mean), 0) as review_score_sum,
                   count(*) filter (where review_score_mean <= 2) as low_review_orders,
                   count(*) filter (where order_status = 'delivered') as delivered_orders,
                   count(*) filter (where order_status = 'delivered' and review_score_mean is not null) as delivered_reviewed_orders,
                   count(*) filter (where is_delivery_label_eligible) as eligible_orders,
                   count(*) filter (where is_delayed_calendar_day) as late_orders
            from gold.dashboard_customer_order_base where {where}
            group by 1 order by orders desc, label
        """, parameters(start, end))
    return {"comparison": {"current": current, "previous": previous,
                            "current_rates": current_rates, "previous_rates": previous_rates,
                            "mom": changes},
            "trend": trend, "segments": segments,
            "delivery_reviews": delivery_reviews, "breakdowns": breakdowns}


def prediction_data(connection: duckdb.DuckDBPyConnection,
                    raw: dict[str, list[str]]) -> dict:
    metadata = json.loads(PREDICTION_METADATA.read_text(encoding="utf-8"))
    months = [row["month_key"] for row in rows(connection, """
        select distinct strftime(prediction_cutoff_ts, '%Y%m') as month_key
        from gold.fact_delivery_predictions order by 1
    """)]
    states = [row["customer_state"] for row in rows(connection, """
        select distinct customer_state from gold.fact_delivery_predictions order by 1
    """)]
    month = raw.get("month", ["all"])[0]
    state = raw.get("state", ["all"])[0]
    order_id = raw.get("order_id", [""])[0].strip().lower()
    action = raw.get("action", ["all"])[0]
    if month != "all" and month not in months:
        raise ValueError("Prediction month is outside the historical demo cohort")
    if state != "all" and state not in states:
        raise ValueError("Unknown prediction customer state")
    if order_id and (len(order_id) != 32 or any(char not in "0123456789abcdef" for char in order_id)):
        raise ValueError("Order ID must contain 32 hexadecimal characters")
    if action not in ("all", "manual_call", "automated_message", "none"):
        raise ValueError("Unknown operational action filter")
    where = "(? = 'all' or strftime(prediction_cutoff_ts, '%Y%m') = ?) and (? = 'all' or customer_state = ?) and (? = '' or order_id = ?)"
    parameters = [month, month, state, state, order_id, order_id]
    summary = rows(connection, f"""
        select count(*) as orders,
               count(*) filter (where alert_10pct_frozen_threshold) as frozen_alerts,
               count(*) filter (where predicted_delivery_days < 0) as invalid_regression_outputs,
               count(*) filter (where recommended_action = 'manual_call') as manual_calls,
               count(*) filter (where recommended_action = 'automated_message') as automated_messages,
               count(*) filter (where recommended_action = 'none') as monitor_only,
               avg(predicted_delivery_days) filter (where predicted_delivery_days >= 0) as mean_predicted_days,
               avg(delay_risk_score) as mean_risk_score
        from gold.fact_delivery_predictions where {where}
    """, parameters)[0]
    distribution = rows(connection, f"""
        select least(floor(delay_risk_score * 10)::integer, 9) as score_bin,
               count(*) as orders
        from gold.fact_delivery_predictions where {where}
        group by 1 order by 1
    """, parameters)
    weekly = rows(connection, f"""
        select strftime(date_trunc('week', prediction_cutoff_ts), '%d/%m') as week_start,
               count(*) as orders,
               count(*) filter (where recommended_action = 'manual_call') as manual_calls,
               count(*) filter (where recommended_action = 'automated_message') as automated_messages
        from gold.fact_delivery_predictions where {where}
        group by 1, date_trunc('week', prediction_cutoff_ts)
        order by date_trunc('week', prediction_cutoff_ts)
    """, parameters)
    hotspots = rows(connection, f"""
        select customer_state, count(*) as orders,
               count(*) filter (where recommended_action = 'manual_call') as manual_calls,
               count(*) filter (where recommended_action = 'automated_message') as automated_messages,
               avg(predicted_delivery_days) filter (where predicted_delivery_days >= 0) as mean_predicted_days
        from gold.fact_delivery_predictions where {where}
        group by customer_state
        order by manual_calls desc, automated_messages desc, orders desc limit 8
    """, parameters)
    examples = rows(connection, f"""
        select order_id, strftime(prediction_cutoff_ts, '%Y-%m-%d %H:%M') as purchase_timestamp, customer_state,
               promised_delivery_days, predicted_delivery_days, delay_risk_score as delay_score,
               alert_10pct_frozen_threshold as frozen_alert,
               risk_zone, recommended_action as action,
               strftime(decision_available_at, '%Y-%m-%d %H:%M') as decision_available_at
        from gold.fact_delivery_predictions where {where} and (? = 'all' or recommended_action = ?)
        order by case recommended_action when 'manual_call' then 0 when 'automated_message' then 1 else 2 end,
                 delay_risk_score desc, order_id limit 30
    """, [*parameters, action, action])
    return {
        "filters": {"month": month, "state": state, "order_id": order_id, "action": action},
        "options": {"months": months, "states": states},
        "metadata": metadata,
        "summary": summary,
        "distribution": distribution,
        "weekly": weekly,
        "hotspots": hotspots,
        "orders": examples,
    }


def dashboard_data(connection: duckdb.DuckDBPyConnection, filters: tuple[int, str, str],
                   valid: dict) -> dict:
    month, state, status = filters
    previous_month = shift_month(month, -1)
    start, end = month_bounds(month)
    previous_start, previous_end = month_bounds(previous_month)
    where = "purchase_date_key between ? and ? and (? = 'all' or customer_state = ?) and (? = 'all' or order_status = ?)"
    def parameters(first: int, last: int) -> list:
        return [first, last, state, state, status, status]

    def totals_for(first: int, last: int) -> dict:
        return rows(connection, f"""
        select coalesce(sum(order_count), 0) as orders,
               coalesce(sum(delivered_status_order_count), 0) as delivered_orders,
               coalesce(sum(eligible_delivery_order_count), 0) as eligible_orders,
               coalesce(sum(delayed_calendar_day_order_count), 0) as late_orders,
               coalesce(sum(actual_delivery_days_sum), 0) as delivery_days_sum,
               coalesce(sum(reviewed_order_count), 0) as reviewed_orders,
               coalesce(sum(review_score_sum), 0) as review_score_sum,
               coalesce(sum(ordered_item_value), 0) as ordered_item_value,
               coalesce(sum(ordered_freight_value), 0) as ordered_freight_value
        from gold.dashboard_order_daily where {where}
    """, parameters(first, last))[0]

    current = totals_for(start, end)
    previous = totals_for(previous_start, previous_end)
    def rate(total: dict) -> float | None:
        return float(total["late_orders"]) / total["eligible_orders"] if total["eligible_orders"] else None
    def days(total: dict) -> float | None:
        return float(total["delivery_days_sum"]) / total["eligible_orders"] if total["eligible_orders"] else None
    def relative(name: str) -> float | None:
        old = float(previous[name])
        return (float(current[name]) / old - 1) * 100 if old else None
    def aov(total: dict) -> float | None:
        return float(total["ordered_item_value"]) / total["orders"] if total["orders"] else None
    def review_score(total: dict) -> float | None:
        return float(total["review_score_sum"]) / total["reviewed_orders"] if total["reviewed_orders"] else None
    current_rate, previous_rate = rate(current), rate(previous)
    current_days, previous_days = days(current), days(previous)
    current_aov, previous_aov = aov(current), aov(previous)
    current_review_score, previous_review_score = review_score(current), review_score(previous)
    mom = {
        "orders_percent": relative("orders"),
        "late_orders_percent": relative("late_orders"),
        "late_rate_percentage_points": (current_rate - previous_rate) * 100 if current_rate is not None and previous_rate is not None else None,
        "delivery_days_difference": current_days - previous_days if current_days is not None and previous_days is not None else None,
        "ordered_item_value_percent": relative("ordered_item_value"),
        "aov_percent": (current_aov / previous_aov - 1) * 100 if current_aov is not None and previous_aov else None,
        "review_score_difference": current_review_score - previous_review_score if current_review_score is not None and previous_review_score is not None else None,
    }
    first_trend_month = shift_month(month, -11)
    trend = rows(connection, f"""
        select floor(purchase_date_key / 100)::integer as month_key,
               sum(order_count) as orders,
               sum(eligible_delivery_order_count) as eligible_orders,
               sum(delayed_calendar_day_order_count) as late_orders,
               sum(ordered_item_value) as ordered_item_value,
               sum(reviewed_order_count) as reviewed_orders,
               sum(review_score_sum) as review_score_sum
        from gold.dashboard_order_daily
        where floor(purchase_date_key / 100)::integer between ? and ?
          and (? = 'all' or customer_state = ?)
          and (? = 'all' or order_status = ?)
        group by 1 order by 1
    """, [first_trend_month, month, state, state, status, status])
    overview_states = rows(connection, """
        select customer_state as label,
               coalesce(sum(order_count) filter (where purchase_date_key between ? and ?), 0) as orders,
               coalesce(sum(eligible_delivery_order_count) filter (where purchase_date_key between ? and ?), 0) as eligible_orders,
               coalesce(sum(delayed_calendar_day_order_count) filter (where purchase_date_key between ? and ?), 0) as late_orders,
               coalesce(sum(order_count) filter (where purchase_date_key between ? and ?), 0) as previous_orders,
               coalesce(sum(eligible_delivery_order_count) filter (where purchase_date_key between ? and ?), 0) as previous_eligible_orders,
               coalesce(sum(delayed_calendar_day_order_count) filter (where purchase_date_key between ? and ?), 0) as previous_late_orders
        from gold.dashboard_order_daily
        where purchase_date_key between ? and ?
          and (? = 'all' or customer_state = ?)
          and (? = 'all' or order_status = ?)
        group by 1 order by eligible_orders desc, orders desc, label
    """, [start, end, start, end, start, end,
          previous_start, previous_end, previous_start, previous_end,
          previous_start, previous_end, previous_start, end,
          state, state, status, status])
    dimension_where = "purchase_date_key between ? and ? and (? = 'all' or customer_state = ?) and (? = 'all' or order_status = ?)"
    breakdowns = {}
    for name, column in BREAKDOWN_DIMENSIONS.items():
        breakdowns[name] = rows(connection, f"""
            select {column} as label, count(*) as orders,
                   count(*) filter (where is_delivery_label_eligible) as eligible_orders,
                   count(*) filter (where is_delayed_calendar_day) as late_orders,
                   coalesce(sum(actual_delivery_days) filter (where is_delivery_label_eligible), 0) as delivery_days_sum,
                   sum(item_price_total) as ordered_item_value
            from gold.dashboard_order_base where {dimension_where}
            group by 1 order by orders desc, label
        """, parameters(start, end))
    delivery_stages = rows(connection, f"""
        select case
                   when grouping(is_delayed_calendar_day) = 1 then 'all'
                   when is_delayed_calendar_day then 'late'
                   else 'on_time'
               end as delivery_group,
               count(*) as eligible_orders,
               count(approval_days) as approval_count,
               avg(approval_days) as approval_days,
               count(seller_preparation_days) as preparation_count,
               avg(seller_preparation_days) as preparation_days,
               count(carrier_transit_days) as transit_count,
               avg(carrier_transit_days) as transit_days,
               avg(actual_delivery_days) as actual_days,
               avg(estimated_delivery_days) as promised_days,
               avg(delivery_delay_days) filter (where is_delayed_calendar_day) as late_delay_days
        from gold.dashboard_order_base
        where {dimension_where} and is_delivery_label_eligible
        group by rollup(is_delayed_calendar_day)
    """, parameters(start, end))
    delivery_matrix = {}
    for column in MATRIX_DIMENSIONS:
        delivery_matrix[column] = rows(connection, f"""
            select {column} as label, promise_window_band,
                   count(*) filter (where is_delivery_label_eligible) as eligible_orders,
                   count(*) filter (where is_delayed_calendar_day) as late_orders
            from gold.dashboard_order_base where {dimension_where}
            group by 1, 2 order by 1, 2
        """, parameters(start, end))
    category_where = "(? = 'all' or customer_state = ?) and (? = 'all' or order_status = ?)"
    categories = rows(connection, f"""
        select category_name,
               coalesce(sum(order_item_count) filter (where purchase_date_key between ? and ?), 0) as item_lines,
               coalesce(sum(orders_with_category) filter (where purchase_date_key between ? and ?), 0) as orders_with_category,
               coalesce(sum(ordered_item_value) filter (where purchase_date_key between ? and ?), 0) as ordered_item_value,
               coalesce(sum(ordered_item_value) filter (where purchase_date_key between ? and ?), 0) as previous_item_value
        from gold.dashboard_category_daily
        where purchase_date_key between ? and ? and {category_where}
        group by 1 having item_lines > 0
        order by ordered_item_value desc, category_name
    """, [start, end, start, end, start, end, previous_start, previous_end,
          previous_start, end, state, state, status, status])
    category_trend = rows(connection, f"""
        select floor(purchase_date_key / 100)::integer as month_key, category_name,
               sum(order_item_count) as item_lines,
               sum(ordered_item_value) as ordered_item_value
        from gold.dashboard_category_daily
        where floor(purchase_date_key / 100)::integer between ? and ?
          and {category_where}
        group by 1, 2 order by 1, 2
    """, [first_trend_month, month, state, state, status, status])
    seller_states = rows(connection, f"""
        select seller_state, count(distinct seller_key) as active_sellers,
               sum(order_item_count) as item_lines,
               sum(ordered_item_value) as ordered_item_value
        from gold.dashboard_seller_daily where {where}
        group by 1 order by ordered_item_value desc, seller_state
    """, parameters(start, end))
    sellers = rows(connection, f"""
        select seller_id, seller_city, seller_state,
               coalesce(sum(order_item_count) filter (where purchase_date_key between ? and ?), 0) as item_lines,
               coalesce(sum(orders_with_seller) filter (where purchase_date_key between ? and ?), 0) as orders_with_seller,
               coalesce(sum(ordered_item_value) filter (where purchase_date_key between ? and ?), 0) as ordered_item_value,
               coalesce(sum(ordered_item_value) filter (where purchase_date_key between ? and ?), 0) as previous_item_value
        from gold.dashboard_seller_daily
        where purchase_date_key between ? and ? and {category_where}
        group by 1, 2, 3 having item_lines > 0
        order by ordered_item_value desc, seller_id limit 20
    """, [start, end, start, end, start, end, previous_start, previous_end,
          previous_start, end, state, state, status, status])
    previous_category_summary = rows(connection, f"""
        select coalesce(sum(order_item_count), 0) as item_lines,
               count(distinct category_name) as active_categories
        from gold.dashboard_category_daily where {where}
    """, parameters(previous_start, previous_end))[0]
    previous_seller_summary = rows(connection, f"""
        select count(distinct seller_key) as active_sellers
        from gold.dashboard_seller_daily where {where}
    """, parameters(previous_start, previous_end))[0]
    product_summary = {
        "item_lines": sum(row["item_lines"] for row in categories),
        "previous_item_lines": previous_category_summary["item_lines"],
        "active_categories": len(categories),
        "previous_active_categories": previous_category_summary["active_categories"],
        "active_sellers": sum(row["active_sellers"] for row in seller_states),
        "previous_active_sellers": previous_seller_summary["active_sellers"],
        "top_five_category_share": (
            sum(float(row["ordered_item_value"]) for row in categories[:5])
            / float(current["ordered_item_value"])
            if current["ordered_item_value"] else None
        ),
        "top_ten_seller_share": (
            sum(float(row["ordered_item_value"]) for row in sellers[:10])
            / float(current["ordered_item_value"])
            if current["ordered_item_value"] else None
        ),
    }
    month_is_partial = month not in valid["complete_months"]
    return {
        "filters": {"month": month, "state": state, "status": status},
        "comparison": {
            "month": month, "previous_month": previous_month,
            "current": current, "previous": previous, "mom": mom,
            "current_late_rate": current_rate, "previous_late_rate": previous_rate,
            "current_delivery_days": current_days, "previous_delivery_days": previous_days,
            "current_aov": current_aov, "previous_aov": previous_aov,
            "current_review_score": current_review_score,
            "previous_review_score": previous_review_score,
            "month_is_partial": month_is_partial,
        },
        "trend": trend,
        "overview_states": overview_states,
        "breakdowns": breakdowns,
        "delivery_stages": delivery_stages,
        "delivery_matrix": delivery_matrix,
        "categories": categories,
        "category_trend": category_trend,
        "seller_states": seller_states,
        "sellers": sellers,
        "product_summary": product_summary,
        "customer": customer_experience_data(connection, filters),
        "definition": "Purchase-date cohort; late = actual delivery calendar date after estimated date; late-rate denominator = eligible delivered orders.",
    }


class DashboardHandler(BaseHTTPRequestHandler):
    database = DEFAULT_DATABASE

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=float).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        if request.path in ASSETS:
            filename, content_type = ASSETS[request.path]
            body = (Path(__file__).parent / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if request.path not in ("/api/options", "/api/dashboard", "/api/predictions"):
            self.send_error(404)
            return
        try:
            if request.path == "/api/predictions":
                with duckdb.connect(str(self.database), read_only=True) as connection:
                    payload = prediction_data(connection, parse_qs(request.query))
            else:
                with duckdb.connect(str(self.database), read_only=True) as connection:
                    valid = options(connection)
                    if request.path == "/api/options":
                        payload = {**valid, "database_updated_at": datetime.fromtimestamp(
                            self.database.stat().st_mtime
                        ).isoformat(timespec="minutes")}
                    else:
                        filters = parse_filters(parse_qs(request.query), valid)
                        payload = dashboard_data(connection, filters, valid)
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
            return
        except (duckdb.Error, OSError) as error:
            self.send_json(503, {"error": "Gold dashboard data is unavailable", "detail": str(error)})
            return
        self.send_json(200, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    if not args.database.exists():
        parser.error(f"DuckDB database not found: {args.database}")
    DashboardHandler.database = args.database
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print(f"Olist dashboard: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

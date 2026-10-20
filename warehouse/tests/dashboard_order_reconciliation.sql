with source_totals as (
    select
        count(*) as orders,
        count(*) filter (where is_delivery_label_eligible) as eligible,
        count(*) filter (where is_delayed_calendar_day) as delayed,
        coalesce(sum(actual_delivery_days) filter (where is_delivery_label_eligible), 0) as days,
        count(review_score_mean) as reviewed_orders,
        coalesce(sum(review_score_mean), 0) as review_scores,
        sum(item_price_total) as item_value,
        sum(freight_total) as freight_value
    from {{ ref('fact_delivery_performance') }}
), base_totals as (
    select
        count(*) as orders,
        count(*) filter (where is_delivery_label_eligible) as eligible,
        count(*) filter (where is_delayed_calendar_day) as delayed,
        coalesce(sum(actual_delivery_days) filter (where is_delivery_label_eligible), 0) as days,
        count(review_score_mean) as reviewed_orders,
        coalesce(sum(review_score_mean), 0) as review_scores,
        sum(item_price_total) as item_value,
        sum(freight_total) as freight_value
    from {{ ref('dashboard_order_base') }}
), daily_totals as (
    select
        sum(order_count) as orders,
        sum(eligible_delivery_order_count) as eligible,
        sum(delayed_calendar_day_order_count) as delayed,
        sum(actual_delivery_days_sum) as days,
        sum(reviewed_order_count) as reviewed_orders,
        sum(review_score_sum) as review_scores,
        sum(ordered_item_value) as item_value,
        sum(ordered_freight_value) as freight_value
    from {{ ref('dashboard_order_daily') }}
), all_totals as (
    select 'base' as stage, * from base_totals
    union all
    select 'daily' as stage, * from daily_totals
)
select a.stage
from all_totals a cross join source_totals s
where a.orders <> s.orders
   or a.eligible <> s.eligible
   or a.delayed <> s.delayed
   or abs(a.days - s.days) > 0.00001
   or a.reviewed_orders <> s.reviewed_orders
   or abs(a.review_scores - s.review_scores) > 0.00001
   or abs(a.item_value - s.item_value) > 0.01
   or abs(a.freight_value - s.freight_value) > 0.01
union all
select 'invalid_daily_counts'
from {{ ref('dashboard_order_daily') }}
where delayed_calendar_day_order_count > eligible_delivery_order_count
   or eligible_delivery_order_count > delivered_status_order_count
   or delivered_status_order_count > order_count
union all
select 'duplicate_daily_grain'
from {{ ref('dashboard_order_daily') }}
group by purchase_date_key, customer_state, order_status
having count(*) > 1

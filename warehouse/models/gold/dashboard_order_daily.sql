-- Grain: purchase date x customer state x order status.
-- Store additive numerators/denominators. A dashboard must recompute ratios
-- after applying filters rather than summing or averaging daily percentages.
select
    purchase_date_key,
    customer_state,
    order_status,
    count(*) as order_count,
    count(*) filter (where order_status = 'delivered') as delivered_status_order_count,
    count(*) filter (where is_delivery_label_eligible) as eligible_delivery_order_count,
    count(*) filter (where is_delayed_calendar_day) as delayed_calendar_day_order_count,
    coalesce(sum(actual_delivery_days) filter (where is_delivery_label_eligible), 0)
        as actual_delivery_days_sum,
    count(review_score_mean) as reviewed_order_count,
    coalesce(sum(review_score_mean), 0) as review_score_sum,
    sum(item_price_total) as ordered_item_value,
    sum(freight_total) as ordered_freight_value
from {{ ref('dashboard_order_base') }}
group by purchase_date_key, customer_state, order_status

-- One row per order. Exact customer state comes from the order's customer
-- record; dim_geolocation intentionally has no authoritative state attribute.
select
    f.order_id,
    f.purchase_date_key,
    f.delivered_date_key,
    dayofweek(f.order_purchase_timestamp) as purchase_weekday,
    f.order_status,
    coalesce(c.customer_state, '<missing>') as customer_state,
    f.item_count,
    case
        when f.item_count = 0 then '0 items'
        when f.item_count = 1 then '1 item'
        when f.item_count = 2 then '2 items'
        else '3+ items'
    end as order_size_band,
    case
        when f.estimated_delivery_days is null then 'unknown'
        when f.estimated_delivery_days < 0 then 'invalid'
        when f.estimated_delivery_days < 14 then '<14 days'
        when f.estimated_delivery_days < 30 then '14-29 days'
        else '30+ days'
    end as promise_window_band,
    f.is_delivery_label_eligible,
    f.is_delayed_calendar_day,
    f.approval_days,
    f.seller_preparation_days,
    f.carrier_transit_days,
    f.actual_delivery_days,
    f.estimated_delivery_days,
    f.delivery_delay_days,
    f.review_score_mean,
    f.item_price_total,
    f.freight_total
from {{ ref('fact_delivery_performance') }} f
join {{ ref('stg_orders') }} o on f.order_id = o.order_id
join {{ ref('stg_customers') }} c on o.customer_id = c.customer_id

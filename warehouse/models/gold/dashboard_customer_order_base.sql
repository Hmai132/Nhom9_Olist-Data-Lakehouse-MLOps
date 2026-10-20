-- Grain: one order. Buyer identity is customer_unique_id via customer_key.
-- Sequence and first observed date are calculated over the full extract,
-- before dashboard filters, so a filter cannot redefine a customer's history.
with numbered as (
    select
        f.order_id,
        f.customer_key,
        f.order_purchase_timestamp,
        f.purchase_date_key,
        row_number() over (
            partition by f.customer_key
            order by f.order_purchase_timestamp, f.order_id
        ) as observed_order_number,
        min(f.purchase_date_key) over (partition by f.customer_key)
            as first_observed_purchase_date_key
    from {{ ref('fact_delivery_performance') }} f
)
select
    n.order_id,
    n.customer_key,
    n.purchase_date_key,
    n.first_observed_purchase_date_key,
    n.observed_order_number,
    b.customer_state,
    b.order_status,
    b.purchase_weekday,
    b.order_size_band,
    b.promise_window_band,
    b.is_delivery_label_eligible,
    b.is_delayed_calendar_day,
    b.review_score_mean,
    b.item_price_total
from numbered n
join {{ ref('dashboard_order_base') }} b on n.order_id = b.order_id

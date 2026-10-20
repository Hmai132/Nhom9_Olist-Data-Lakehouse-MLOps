-- Accumulating snapshot: exactly one row per order, with milestones that can
-- be populated as the order progresses. Olist is a static historical extract.
with items as (
    select
        order_id,
        count(*) as item_count,
        count(distinct product_id) as distinct_product_count,
        count(distinct seller_id) as distinct_seller_count,
        sum(price) as item_price_total,
        sum(freight_value) as freight_total
    from {{ ref('stg_order_items') }}
    group by order_id
), payments as (
    select
        order_id,
        count(*) as payment_count,
        sum(payment_value) as payment_total,
        count(*) filter (where is_nonpositive_payment) as nonpositive_payment_count
    from {{ ref('stg_order_payments') }}
    group by order_id
), reviews as (
    select
        order_id,
        count(*) as review_count,
        avg(review_score) as review_score_mean,
        arg_max(review_score, review_answer_timestamp) as latest_review_score
    from {{ ref('stg_order_reviews') }}
    group by order_id
)
select
    o.order_id,
    md5(c.customer_unique_id) as customer_key,
    md5(c.customer_zip_code_prefix) as customer_geolocation_key,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    cast(strftime(o.order_purchase_timestamp, '%Y%m%d') as integer) as purchase_date_key,
    case when o.order_approved_at is not null
        then cast(strftime(o.order_approved_at, '%Y%m%d') as integer)
    end as approval_date_key,
    case when o.order_delivered_carrier_date is not null
        then cast(strftime(o.order_delivered_carrier_date, '%Y%m%d') as integer)
    end as carrier_date_key,
    case when o.order_delivered_customer_date is not null
        then cast(strftime(o.order_delivered_customer_date, '%Y%m%d') as integer)
    end as delivered_date_key,
    cast(strftime(o.order_estimated_delivery_date, '%Y%m%d') as integer) as estimated_date_key,
    coalesce(i.item_count, 0) as item_count,
    coalesce(i.distinct_product_count, 0) as distinct_product_count,
    coalesce(i.distinct_seller_count, 0) as distinct_seller_count,
    coalesce(i.item_price_total, 0) as item_price_total,
    coalesce(i.freight_total, 0) as freight_total,
    coalesce(p.payment_count, 0) as payment_count,
    coalesce(p.payment_total, 0) as payment_total,
    coalesce(p.nonpositive_payment_count, 0) as nonpositive_payment_count,
    coalesce(r.review_count, 0) as review_count,
    r.review_score_mean,
    r.latest_review_score,
    case when o.order_approved_at >= o.order_purchase_timestamp
        then date_diff('second', o.order_purchase_timestamp, o.order_approved_at) / 86400.0
    end as approval_days,
    case when o.order_delivered_carrier_date >= o.order_approved_at
        then date_diff('second', o.order_approved_at, o.order_delivered_carrier_date) / 86400.0
    end as seller_preparation_days,
    case when o.order_delivered_customer_date >= o.order_delivered_carrier_date
        then date_diff('second', o.order_delivered_carrier_date, o.order_delivered_customer_date) / 86400.0
    end as carrier_transit_days,
    case when o.is_delivery_label_eligible
        then date_diff('second', o.order_purchase_timestamp, o.order_delivered_customer_date) / 86400.0
    end as actual_delivery_days,
    date_diff('second', o.order_purchase_timestamp, o.order_estimated_delivery_date) / 86400.0
        as estimated_delivery_days,
    case when o.is_delivery_label_eligible
        then date_diff('second', o.order_estimated_delivery_date, o.order_delivered_customer_date) / 86400.0
    end as delivery_delay_days,
    case when o.is_delivery_label_eligible
        then o.order_delivered_customer_date > o.order_estimated_delivery_date
    end as is_delayed_timestamp,
    case when o.is_delivery_label_eligible
        then cast(o.order_delivered_customer_date as date) > cast(o.order_estimated_delivery_date as date)
    end as is_delayed_calendar_day,
    o.is_delivery_label_eligible,
    o.is_delivered_missing_delivery_date,
    o.is_terminal_status_with_delivery_date,
    o.is_approval_before_purchase,
    o.is_carrier_before_approval,
    o.is_customer_before_carrier
from {{ ref('stg_orders') }} o
left join {{ ref('stg_customers') }} c on o.customer_id = c.customer_id
left join items i on o.order_id = i.order_id
left join payments p on o.order_id = p.order_id
left join reviews r on o.order_id = r.order_id

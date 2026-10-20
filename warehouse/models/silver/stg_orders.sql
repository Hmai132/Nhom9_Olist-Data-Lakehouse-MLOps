with typed as (
    select
        nullif(trim(order_id), '') as order_id,
        nullif(trim(customer_id), '') as customer_id,
        nullif(trim(order_status), '') as order_status,
        try_cast(order_purchase_timestamp as timestamp) as order_purchase_timestamp,
        try_cast(order_approved_at as timestamp) as order_approved_at,
        try_cast(order_delivered_carrier_date as timestamp) as order_delivered_carrier_date,
        try_cast(order_delivered_customer_date as timestamp) as order_delivered_customer_date,
        try_cast(order_estimated_delivery_date as timestamp) as order_estimated_delivery_date
    from {{ source('bronze', 'orders') }}
)
select
    *,
    order_status = 'delivered' and order_delivered_customer_date is null
        as is_delivered_missing_delivery_date,
    order_status in ('canceled', 'unavailable') and order_delivered_customer_date is not null
        as is_terminal_status_with_delivery_date,
    coalesce(order_approved_at < order_purchase_timestamp, false)
        as is_approval_before_purchase,
    coalesce(order_delivered_carrier_date < order_approved_at, false)
        as is_carrier_before_approval,
    coalesce(order_delivered_customer_date < order_delivered_carrier_date, false)
        as is_customer_before_carrier,
    order_status = 'delivered'
        and order_purchase_timestamp is not null
        and order_delivered_customer_date is not null
        and order_estimated_delivery_date is not null
        as is_delivery_label_eligible
from typed

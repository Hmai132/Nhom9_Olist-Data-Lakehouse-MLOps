with event_dates as (
    select cast(order_purchase_timestamp as date) as date_day from {{ ref('stg_orders') }}
    union all select cast(order_approved_at as date) from {{ ref('stg_orders') }}
    union all select cast(order_delivered_carrier_date as date) from {{ ref('stg_orders') }}
    union all select cast(order_delivered_customer_date as date) from {{ ref('stg_orders') }}
    union all select cast(order_estimated_delivery_date as date) from {{ ref('stg_orders') }}
    union all select cast(shipping_limit_date as date) from {{ ref('stg_order_items') }}
), bounds as (
    select min(date_day) as first_day, max(date_day) as last_day
    from event_dates
), calendar as (
    select cast(day_value as date) as date_day
    from bounds, generate_series(first_day, last_day, interval 1 day) as days(day_value)
)
select
    cast(strftime(date_day, '%Y%m%d') as integer) as date_key,
    date_day,
    year(date_day) as year,
    quarter(date_day) as quarter,
    month(date_day) as month,
    day(date_day) as day_of_month,
    dayofweek(date_day) as day_of_week,
    dayofweek(date_day) in (0, 6) as is_weekend
from calendar

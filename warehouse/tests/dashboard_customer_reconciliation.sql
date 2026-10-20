with source_totals as (
    select count(*) as orders, count(distinct customer_key) as buyers,
           sum(item_price_total) as item_value,
           count(review_score_mean) as reviewed_orders
    from {{ ref('fact_delivery_performance') }}
), customer_totals as (
    select count(*) as orders, count(distinct customer_key) as buyers,
           sum(item_price_total) as item_value,
           count(review_score_mean) as reviewed_orders,
           count(*) filter (where observed_order_number = 1) as first_orders
    from {{ ref('dashboard_customer_order_base') }}
)
select 'customer_totals_mismatch' as problem
from source_totals s cross join customer_totals c
where s.orders <> c.orders or s.buyers <> c.buyers
   or c.first_orders <> c.buyers
   or s.reviewed_orders <> c.reviewed_orders
   or abs(s.item_value - c.item_value) > 0.01
union all
select 'invalid_customer_sequence'
from {{ ref('dashboard_customer_order_base') }}
where observed_order_number < 1
   or first_observed_purchase_date_key > purchase_date_key
union all
select 'duplicate_customer_order_grain'
from {{ ref('dashboard_customer_order_base') }}
group by order_id having count(*) > 1

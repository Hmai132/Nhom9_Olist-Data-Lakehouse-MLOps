with source_totals as (
    select count(*) as items, sum(price) as item_value, sum(freight_value) as freight_value
    from {{ ref('fact_order_item') }}
), category_totals as (
    select
        sum(order_item_count) as items,
        sum(ordered_item_value) as item_value,
        sum(ordered_freight_value) as freight_value
    from {{ ref('dashboard_category_daily') }}
)
select 'category_totals_mismatch' as problem
from source_totals s cross join category_totals c
where s.items <> c.items
   or abs(s.item_value - c.item_value) > 0.01
   or abs(s.freight_value - c.freight_value) > 0.01
union all
select 'invalid_category_counts'
from {{ ref('dashboard_category_daily') }}
where orders_with_category > order_item_count or orders_with_category < 1
union all
select 'duplicate_category_grain'
from {{ ref('dashboard_category_daily') }}
group by purchase_date_key, customer_state, order_status, category_name
having count(*) > 1

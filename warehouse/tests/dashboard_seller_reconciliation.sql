with source_totals as (
    select count(*) as items, sum(price) as item_value, sum(freight_value) as freight_value
    from {{ ref('fact_order_item') }}
), seller_totals as (
    select sum(order_item_count) as items,
           sum(ordered_item_value) as item_value,
           sum(ordered_freight_value) as freight_value
    from {{ ref('dashboard_seller_daily') }}
)
select 'seller_totals_mismatch' as problem
from source_totals s cross join seller_totals d
where s.items <> d.items
   or abs(s.item_value - d.item_value) > 0.01
   or abs(s.freight_value - d.freight_value) > 0.01
union all
select 'invalid_seller_counts'
from {{ ref('dashboard_seller_daily') }}
where orders_with_seller > order_item_count or orders_with_seller < 1
union all
select 'duplicate_seller_grain'
from {{ ref('dashboard_seller_daily') }}
group by purchase_date_key, customer_state, order_status, seller_key
having count(*) > 1

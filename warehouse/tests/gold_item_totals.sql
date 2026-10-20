with item_totals as (
    select
        order_id,
        count(*) as item_count,
        sum(price) as price_total,
        sum(freight_value) as freight_total
    from {{ ref('fact_order_item') }}
    group by order_id
)
select f.order_id
from {{ ref('fact_delivery_performance') }} f
left join item_totals i on f.order_id = i.order_id
where f.item_count <> coalesce(i.item_count, 0)
   or abs(f.item_price_total - coalesce(i.price_total, 0)) > 0.01
   or abs(f.freight_total - coalesce(i.freight_total, 0)) > 0.01

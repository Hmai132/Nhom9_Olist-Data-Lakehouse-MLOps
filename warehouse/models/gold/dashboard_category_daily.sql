-- Grain: purchase date x customer state x order status x product category.
-- Only item-grain money is summed here; order-level values are never summed
-- after the order-to-item join. orders_with_category is non-additive across
-- categories because one order can contain products from multiple categories.
select
    o.purchase_date_key,
    o.customer_state,
    o.order_status,
    coalesce(p.category_name, '<missing>') as category_name,
    count(*) as order_item_count,
    count(distinct i.order_id) as orders_with_category,
    sum(i.price) as ordered_item_value,
    sum(i.freight_value) as ordered_freight_value
from {{ ref('fact_order_item') }} i
join {{ ref('dashboard_order_base') }} o on i.order_id = o.order_id
join {{ ref('dim_product') }} p on i.product_key = p.product_key
group by o.purchase_date_key, o.customer_state, o.order_status,
         coalesce(p.category_name, '<missing>')

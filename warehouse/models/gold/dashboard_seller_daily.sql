-- Grain: purchase date x customer state x order status x seller.
-- Item measures are additive. Orders with a seller are distinct only within
-- that seller; they cannot be summed across sellers when an order is multi-seller.
select
    o.purchase_date_key,
    o.customer_state,
    o.order_status,
    i.seller_key,
    s.seller_id,
    s.seller_city,
    s.seller_state,
    count(*) as order_item_count,
    count(distinct i.order_id) as orders_with_seller,
    sum(i.price) as ordered_item_value,
    sum(i.freight_value) as ordered_freight_value
from {{ ref('fact_order_item') }} i
join {{ ref('dashboard_order_base') }} o on i.order_id = o.order_id
join {{ ref('dim_seller') }} s on i.seller_key = s.seller_key
group by o.purchase_date_key, o.customer_state, o.order_status,
         i.seller_key, s.seller_id, s.seller_city, s.seller_state

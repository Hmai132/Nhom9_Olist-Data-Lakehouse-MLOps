-- Transaction fact at item grain. Product and seller keys stay here; putting
-- either key on the order-grain delivery fact would duplicate delivery measures.
select
    md5(order_id || '|' || cast(order_item_id as varchar)) as order_item_key,
    order_id,
    order_item_id,
    md5(product_id) as product_key,
    md5(seller_id) as seller_key,
    case when shipping_limit_date is not null
        then cast(strftime(shipping_limit_date, '%Y%m%d') as integer)
    end as shipping_limit_date_key,
    price,
    freight_value
from {{ ref('stg_order_items') }}

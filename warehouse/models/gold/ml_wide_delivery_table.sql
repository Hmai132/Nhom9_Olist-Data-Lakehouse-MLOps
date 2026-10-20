-- Point-of-order feature table. Every feature is intended to be known at
-- purchase time; actual milestones and reviews are exposed only as targets
-- in the delivery fact and are deliberately absent from feature_* columns.
with product_features as (
    select
        i.order_id,
        sum(coalesce(p.product_weight_g, 0)) as total_weight_g,
        count(*) filter (where p.product_weight_g is null) as missing_weight_items,
        count(distinct p.product_category_name) as category_count
    from {{ ref('stg_order_items') }} i
    left join {{ ref('dim_product') }} p
        on md5(i.product_id) = p.product_key
    group by i.order_id
), order_sellers as (
    select distinct order_id, seller_id
    from {{ ref('stg_order_items') }}
), seller_routes as (
    select
        os.order_id,
        case when customer_geo.has_coordinate and seller_geo.has_coordinate then
            2 * 6371.0 * asin(sqrt(least(1.0,
                pow(sin(radians(seller_geo.latitude - customer_geo.latitude) / 2), 2)
                + cos(radians(customer_geo.latitude)) * cos(radians(seller_geo.latitude))
                  * pow(sin(radians(seller_geo.longitude - customer_geo.longitude) / 2), 2)
            )))
        end as straight_line_km,
        c.customer_state = s.seller_state as is_same_state
    from order_sellers os
    join {{ ref('stg_orders') }} o on os.order_id = o.order_id
    join {{ ref('stg_customers') }} c on o.customer_id = c.customer_id
    join {{ ref('stg_sellers') }} s on os.seller_id = s.seller_id
    left join {{ ref('dim_geolocation') }} customer_geo
        on md5(c.customer_zip_code_prefix) = customer_geo.geolocation_key
    left join {{ ref('dim_geolocation') }} seller_geo
        on md5(s.seller_zip_code_prefix) = seller_geo.geolocation_key
), route_features as (
    select
        order_id,
        avg(straight_line_km) as mean_seller_distance_km,
        count(*) filter (where straight_line_km is null) as sellers_missing_distance,
        avg(cast(is_same_state as double)) as same_state_seller_share
    from seller_routes
    group by order_id
)
select
    f.order_id,
    f.order_purchase_timestamp as prediction_cutoff_ts,
    month(f.order_purchase_timestamp) as feature_purchase_month,
    dayofweek(f.order_purchase_timestamp) as feature_purchase_day_of_week,
    hour(f.order_purchase_timestamp) as feature_purchase_hour,
    c.customer_state as feature_customer_state,
    c.customer_zip_code_prefix as feature_customer_zip_code_prefix,
    f.estimated_delivery_days as feature_promised_delivery_days,
    f.item_count as feature_item_count,
    f.distinct_product_count as feature_product_count,
    f.distinct_seller_count as feature_seller_count,
    f.item_price_total as feature_item_price_total,
    f.freight_total as feature_freight_total,
    pf.total_weight_g as feature_total_weight_g,
    coalesce(pf.missing_weight_items, 0) as feature_missing_weight_items,
    coalesce(pf.category_count, 0) as feature_category_count,
    rf.mean_seller_distance_km as feature_mean_seller_distance_km,
    coalesce(rf.sellers_missing_distance, 0) as feature_sellers_missing_distance,
    rf.same_state_seller_share as feature_same_state_seller_share,
    f.is_delivery_label_eligible as is_label_eligible,
    f.actual_delivery_days as target_actual_delivery_days,
    f.is_delayed_timestamp as target_is_delayed_timestamp,
    f.is_delayed_calendar_day as target_is_delayed_calendar_day
from {{ ref('fact_delivery_performance') }} f
join {{ ref('stg_orders') }} o on f.order_id = o.order_id
join {{ ref('stg_customers') }} c on o.customer_id = c.customer_id
left join product_features pf on f.order_id = pf.order_id
left join route_features rf on f.order_id = rf.order_id

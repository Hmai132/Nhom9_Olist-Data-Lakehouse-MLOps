with all_zip_codes as (
    select geolocation_zip_code_prefix as zip_code_prefix
    from {{ ref('geolocation_by_zip') }}
    union
    select customer_zip_code_prefix from {{ ref('stg_customers') }}
    union
    select seller_zip_code_prefix from {{ ref('stg_sellers') }}
)
select
    md5(z.zip_code_prefix) as geolocation_key,
    z.zip_code_prefix,
    g.latitude,
    g.longitude,
    g.latitude is not null and g.longitude is not null as has_coordinate,
    coalesce(g.source_rows, 0) as source_rows,
    coalesce(g.distinct_valid_rows, 0) as distinct_valid_rows,
    coalesce(g.out_of_bounds_rows, 0) as out_of_bounds_rows,
    coalesce(g.has_state_conflict, false) as has_state_conflict,
    coalesce(g.has_city_name_conflict, false) as has_city_name_conflict
from all_zip_codes z
left join {{ ref('geolocation_by_zip') }} g
    on z.zip_code_prefix = g.geolocation_zip_code_prefix
where z.zip_code_prefix is not null

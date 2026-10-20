with raw_counts as (
    select
        geolocation_zip_code_prefix,
        count(*) as source_rows,
        count(*) filter (where not is_within_brazil_bounds) as out_of_bounds_rows,
        count(distinct geolocation_state) as state_count,
        count(distinct geolocation_city) as city_name_count
    from {{ ref('stg_geolocation') }}
    group by 1
), valid_distinct as (
    select distinct
        geolocation_zip_code_prefix,
        geolocation_lat,
        geolocation_lng,
        geolocation_city,
        geolocation_state
    from {{ ref('stg_geolocation') }}
    where is_within_brazil_bounds
), representative as (
    select
        geolocation_zip_code_prefix,
        median(geolocation_lat) as latitude,
        median(geolocation_lng) as longitude,
        count(*) as distinct_valid_rows
    from valid_distinct
    group by 1
)
select
    raw_counts.geolocation_zip_code_prefix,
    representative.latitude,
    representative.longitude,
    raw_counts.source_rows,
    coalesce(representative.distinct_valid_rows, 0) as distinct_valid_rows,
    raw_counts.out_of_bounds_rows,
    raw_counts.state_count,
    raw_counts.city_name_count,
    raw_counts.state_count > 1 as has_state_conflict,
    raw_counts.city_name_count > 1 as has_city_name_conflict
from raw_counts
left join representative using (geolocation_zip_code_prefix)

select
    lpad(nullif(trim(geolocation_zip_code_prefix), ''), 5, '0') as geolocation_zip_code_prefix,
    try_cast(geolocation_lat as double) as geolocation_lat,
    try_cast(geolocation_lng as double) as geolocation_lng,
    lower(nullif(trim(geolocation_city), '')) as geolocation_city,
    upper(nullif(trim(geolocation_state), '')) as geolocation_state,
    coalesce(
        try_cast(geolocation_lat as double) between -33.8 and 5.3
        and try_cast(geolocation_lng as double) between -73.99 and -34.7,
        false
    ) as is_within_brazil_bounds
from {{ source('bronze', 'geolocation') }}

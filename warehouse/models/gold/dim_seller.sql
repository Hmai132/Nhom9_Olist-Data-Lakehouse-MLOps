select
    md5(seller_id) as seller_key,
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    seller_state,
    md5(seller_zip_code_prefix) as seller_geolocation_key
from {{ ref('stg_sellers') }}

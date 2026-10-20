select
    nullif(trim(seller_id), '') as seller_id,
    lpad(nullif(trim(seller_zip_code_prefix), ''), 5, '0') as seller_zip_code_prefix,
    lower(nullif(trim(seller_city), '')) as seller_city,
    upper(nullif(trim(seller_state), '')) as seller_state
from {{ source('bronze', 'sellers') }}

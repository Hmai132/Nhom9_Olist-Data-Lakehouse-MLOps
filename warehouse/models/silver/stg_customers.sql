select
    nullif(trim(customer_id), '') as customer_id,
    nullif(trim(customer_unique_id), '') as customer_unique_id,
    lpad(nullif(trim(customer_zip_code_prefix), ''), 5, '0') as customer_zip_code_prefix,
    lower(nullif(trim(customer_city), '')) as customer_city,
    upper(nullif(trim(customer_state), '')) as customer_state
from {{ source('bronze', 'customers') }}

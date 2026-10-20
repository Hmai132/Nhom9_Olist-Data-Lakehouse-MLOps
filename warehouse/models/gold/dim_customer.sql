-- A real buyer is identified by customer_unique_id. The order-specific
-- delivery address is represented separately through dim_geolocation.
select
    md5(customer_unique_id) as customer_key,
    customer_unique_id
from {{ ref('stg_customers') }}
group by customer_unique_id

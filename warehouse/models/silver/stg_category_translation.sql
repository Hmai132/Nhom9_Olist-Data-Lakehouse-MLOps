select
    nullif(trim(product_category_name), '') as product_category_name,
    nullif(trim(product_category_name_english), '') as product_category_name_english
from {{ source('bronze', 'category_translation') }}

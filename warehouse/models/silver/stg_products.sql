select
    nullif(trim(product_id), '') as product_id,
    nullif(trim(product_category_name), '') as product_category_name,
    try_cast(product_name_lenght as integer) as product_name_length,
    try_cast(product_description_lenght as integer) as product_description_length,
    try_cast(product_photos_qty as integer) as product_photos_qty,
    try_cast(product_weight_g as double) as product_weight_g,
    try_cast(product_length_cm as double) as product_length_cm,
    try_cast(product_height_cm as double) as product_height_cm,
    try_cast(product_width_cm as double) as product_width_cm
from {{ source('bronze', 'products') }}

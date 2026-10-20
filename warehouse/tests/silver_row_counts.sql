-- Atomic Silver models retain every Bronze row; cleaning is expressed as
-- typed columns and flags rather than silently dropping observations.
with counts as (
    select 'customers' as dataset,
        (select count(*) from {{ source('bronze', 'customers') }}) as bronze_rows,
        (select count(*) from {{ ref('stg_customers') }}) as silver_rows
    union all select 'sellers',
        (select count(*) from {{ source('bronze', 'sellers') }}),
        (select count(*) from {{ ref('stg_sellers') }})
    union all select 'category_translation',
        (select count(*) from {{ source('bronze', 'category_translation') }}),
        (select count(*) from {{ ref('stg_category_translation') }})
    union all select 'products',
        (select count(*) from {{ source('bronze', 'products') }}),
        (select count(*) from {{ ref('stg_products') }})
    union all select 'orders',
        (select count(*) from {{ source('bronze', 'orders') }}),
        (select count(*) from {{ ref('stg_orders') }})
    union all select 'order_items',
        (select count(*) from {{ source('bronze', 'order_items') }}),
        (select count(*) from {{ ref('stg_order_items') }})
    union all select 'order_payments',
        (select count(*) from {{ source('bronze', 'order_payments') }}),
        (select count(*) from {{ ref('stg_order_payments') }})
    union all select 'order_reviews',
        (select count(*) from {{ source('bronze', 'order_reviews') }}),
        (select count(*) from {{ ref('stg_order_reviews') }})
    union all select 'geolocation',
        (select count(*) from {{ source('bronze', 'geolocation') }}),
        (select count(*) from {{ ref('stg_geolocation') }})
)
select * from counts where bronze_rows <> silver_rows

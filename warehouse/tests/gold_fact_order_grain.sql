select 'delivery_fact' as model, count(*) as actual_rows,
    (select count(*) from {{ ref('stg_orders') }}) as expected_rows
from {{ ref('fact_delivery_performance') }}
having count(*) <> (select count(*) from {{ ref('stg_orders') }})
union all
select 'item_fact', count(*),
    (select count(*) from {{ ref('stg_order_items') }})
from {{ ref('fact_order_item') }}
having count(*) <> (select count(*) from {{ ref('stg_order_items') }})
union all
select 'ml_wide', count(*),
    (select count(*) from {{ ref('stg_orders') }})
from {{ ref('ml_wide_delivery_table') }}
having count(*) <> (select count(*) from {{ ref('stg_orders') }})

select
    nullif(trim(order_id), '') as order_id,
    try_cast(payment_sequential as integer) as payment_sequential,
    nullif(trim(payment_type), '') as payment_type,
    try_cast(payment_installments as integer) as payment_installments,
    try_cast(payment_value as decimal(18, 2)) as payment_value,
    coalesce(try_cast(payment_value as decimal(18, 2)) <= 0, false) as is_nonpositive_payment
from {{ source('bronze', 'order_payments') }}

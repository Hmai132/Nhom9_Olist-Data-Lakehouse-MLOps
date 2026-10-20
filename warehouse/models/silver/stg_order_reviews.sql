select
    nullif(trim(review_id), '') as review_id,
    nullif(trim(order_id), '') as order_id,
    try_cast(review_score as integer) as review_score,
    nullif(trim(review_comment_title), '') as review_comment_title,
    nullif(trim(review_comment_message), '') as review_comment_message,
    try_cast(review_creation_date as timestamp) as review_creation_date,
    try_cast(review_answer_timestamp as timestamp) as review_answer_timestamp
from {{ source('bronze', 'order_reviews') }}

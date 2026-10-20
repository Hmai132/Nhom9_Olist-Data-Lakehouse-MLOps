select order_id
from {{ ref('ml_wide_delivery_table') }}
where (not is_label_eligible and (
    target_actual_delivery_days is not null
    or target_is_delayed_timestamp is not null
    or target_is_delayed_calendar_day is not null
))
or (is_label_eligible and (
    target_actual_delivery_days is null
    or target_is_delayed_timestamp is null
    or target_is_delayed_calendar_day is null
))

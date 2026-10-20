# Dashboard metric contract

This is the Olist project's business definition, implemented on the Gold
dashboard marts. The Power BI NotebookLM sources support explicit measures,
star-schema grain, a calendar dimension, and safe ratio denominators; the
specific Olist measures below are project choices. The Overview question flow
(scale, product mix, fulfillment, customer feedback) is informed by Judah
Phillips's *Ecommerce Analytics* in NotebookLM and limited to fields present
in Olist.

All daily marts use **purchase date** as the default date role. Join
`purchase_date_key` to `gold.dim_date.date_key`. Delivery date is a separate
role on `gold.dashboard_order_base.delivered_date_key`; do not silently switch
date roles inside the same visual.

The analytical dashboard compares one selected **calendar purchase month**
with its preceding calendar month under the same state and status filters.
The Overview page also compares late rates for the five customer states with
the most eligible delivered orders in the selected month. Both rates use
state-specific late and eligible counts, with the same filters in each month.
Order, value and item-value-per-order MoM is `(current / previous) - 1` when
previous is nonzero.
Late-rate MoM is `current rate - previous rate` in **percentage points**;
review-score MoM is a difference in score points. Each month's rate and
average are recomputed from that month's summed numerator and denominator.
The UI flags a month as partial if observed purchase dates do not span its
first and last calendar day. It defaults to the latest month spanning both
dates (August 2018 in this extract). This is a coverage heuristic, not proof
that every order in a month is present. Partial-month MoM compares with a full
preceding month and should be interpreted cautiously.

Order-level breakdowns use `dashboard_order_base`: customer state, order
status, number of order item lines (`0`, `1`, `2`, `3+`), promised-delivery window
(`<14`, `14-29`, `30+` days), and purchase weekday. These bands are project
definitions for descriptive analysis, not predictions or course-defined KPIs.
The diagnostic view uses the same one-order grain for milestone durations.
Average approval, seller-preparation and carrier-transit days are computed as
`SUM(valid duration) / COUNT(valid duration)` within eligible delivered orders;
each stage can have a different denominator. Missing or invalid milestones
remain NULL. The late/on-time bars are descriptive comparisons and their
means must not be added together to reconstruct average total delivery days.
Cross-dimension matrix cells recompute late orders / eligible orders within
each customer-state, item-count or weekday × promise-window combination.

| Measure | Definition after date/state/status filters | Source |
| --- | --- | --- |
| Orders placed | `SUM(order_count)` | `gold.dashboard_order_daily` |
| Delivered status orders | `SUM(delivered_status_order_count)` | order daily |
| Eligible delivered orders | `SUM(eligible_delivery_order_count)` | order daily |
| Late orders, calendar day | `SUM(delayed_calendar_day_order_count)` | order daily |
| Actual late rate | late orders / eligible delivered orders, NULL when denominator is zero | order daily |
| Average actual delivery days | `SUM(actual_delivery_days_sum)` / eligible delivered orders, NULL when denominator is zero | order daily |
| Ordered item value | `SUM(ordered_item_value)` | order daily |
| Item value per order (AOV) | ordered item value / orders placed, NULL for zero orders | order daily |
| Reviewed orders | `SUM(reviewed_order_count)`; only non-null order review scores | order daily |
| Average order review score | `SUM(review_score_sum)` / reviewed orders, NULL for zero reviewed orders | order daily |
| Ordered freight value | `SUM(ordered_freight_value)` | order daily |
| Item lines | `SUM(order_item_count)` | `gold.dashboard_category_daily` |
| Orders containing a category | `SUM(orders_with_category)` within one category | category daily |
| Active categories | distinct categories with item lines in the selected month | category daily |
| Active sellers | distinct seller keys with item lines in the selected month | `gold.dashboard_seller_daily` |
| Orders containing a seller | `SUM(orders_with_seller)` within one seller; do not sum across sellers | seller daily |
| Top-ten seller concentration | top-ten seller item value / total filtered item value | seller daily and order daily |
| Unique buyers | `COUNT(DISTINCT customer_key)` within filtered purchase month | `gold.dashboard_customer_order_base` |
| Previously observed buyers | distinct buyers in selected month whose first observed purchase date precedes its first day | customer order base |
| Returning buyer share | previously observed buyers / unique buyers, NULL for zero buyers | customer order base |
| Delivered review coverage | delivered-status orders with non-null order review / delivered-status orders | customer order base |
| Low review share | reviewed orders with order mean review score ≤ 2 / reviewed orders | customer order base |

`Eligible delivered orders` is the denominator of the late rate, not a
headline business KPI. The Overview KPI card displays the number of late
orders and its MoM change; the rate card displays its denominator in supporting
text.

`is_delivery_label_eligible` follows `gold.fact_delivery_performance`: delivered
status with purchase, actual delivery and estimated delivery timestamps.
Cancelled, unavailable and unfinished orders are excluded from the **late-rate
denominator**, but they remain in the total orders placed. Late means the
customer delivery **calendar date** is after the estimated calendar date.
The numerator and denominator must be summed over the current filter context
before division. Never average daily percentages into a monthly percentage.

`ordered_item_value` is the sum of listed item prices on placed orders. It is
not recognized revenue, paid amount, net sales or profit. The order mart's
value is the sum of order-level item totals; the category mart's value is the
sum of item-level prices. These totals reconcile globally, but order totals
must never be summed after joining to item lines.

The Overview category share uses the five largest categories by ordered item
value and one remainder group: total order-level item value minus those five
category values. This retains the long tail and reconciles to the headline
value. An order with items in multiple categories is counted only once in the
order KPIs. Review scores are order-level means from the delivery fact; this
dashboard gives each reviewed order equal weight. Missing reviews stay NULL
and do not enter the review-score denominator.

`orders_with_category` uses `COUNT(DISTINCT order_id)` inside each
date/state/status/category cell. One order can appear in more than one category. Do not sum this
measure **across categories** to report total orders; use the order mart.

`dashboard_seller_daily` has purchase date × customer state × order status ×
seller grain. Its item counts and prices reconcile to `fact_order_item`.
`orders_with_seller` is distinct inside a seller and cannot be added across
sellers: an order can contain multiple sellers. Seller state comes from
`dim_seller`, whereas the global state filter is the customer's state. The
product page does not assign order-level late delivery or review scores to
individual sellers. Category concentration is the observed number of
categories needed to reach at least 80% of filtered item value; it does not
assume that an 80/20 law holds in Olist.

`dashboard_customer_order_base` has one row per order and uses the Gold
customer key derived from `customer_unique_id`. The source `customer_id` is
specific to an order and is unsuitable for identifying repeat buyers. Order
sequence and first observed purchase date are computed over the full extract
before any dashboard state/status filter. A buyer first seen earlier than the
selected month counts as previously observed if they place a filtered order
in that month. Distinct buyers are **not additive** across dates, statuses or
segments. First versus subsequent **orders** are mutually exclusive, but
one buyer can have both types in a month.

These measures describe observed repeat behavior, not retention or churn.
The finite extract truncates buyer histories at both ends, and recent buyers
have less follow-up time. Review scores are order-level means; a missing
review stays NULL. Delivered review coverage uses delivered-status orders,
while average review score and low-review share use all reviewed orders in
the filtered order cohort. The late versus on-time comparison further limits
the cohort to orders with valid delivered and estimated dates. Differences
between those groups are associations, not evidence of a sole cause.

Example Power BI measures when importing `dashboard_order_daily`:

```dax
Orders Placed = SUM(dashboard_order_daily[order_count])
Eligible Delivered Orders = SUM(dashboard_order_daily[eligible_delivery_order_count])
Late Orders = SUM(dashboard_order_daily[delayed_calendar_day_order_count])
Actual Late Rate = DIVIDE([Late Orders], [Eligible Delivered Orders])
Ordered Item Value = SUM(dashboard_order_daily[ordered_item_value])
Item Value per Order = DIVIDE([Ordered Item Value], [Orders Placed])
Reviewed Orders = SUM(dashboard_order_daily[reviewed_order_count])
Average Order Review Score =
    DIVIDE(SUM(dashboard_order_daily[review_score_sum]), [Reviewed Orders])
Average Actual Delivery Days =
    DIVIDE(SUM(dashboard_order_daily[actual_delivery_days_sum]), [Eligible Delivered Orders])
```

Use a single active relationship from `dim_date[date_key]` to
`dashboard_order_daily[purchase_date_key]` for purchase-time visuals. A
delivery-time visual should use the delivery date role from the order base
with an explicit relationship/measure; the daily purchase mart cannot answer
delivery-date questions. Actual business KPIs here are separate from the
exploratory ML scores and risk bands.

Equivalent DuckDB query for a purchase-date range (the same summed numerator
and denominator apply when adding customer-state or status filters):

```sql
select
    sum(order_count) as orders_placed,
    sum(eligible_delivery_order_count) as eligible_delivered_orders,
    sum(delayed_calendar_day_order_count) as late_orders,
    sum(delayed_calendar_day_order_count) * 1.0
        / nullif(sum(eligible_delivery_order_count), 0) as actual_late_rate,
    sum(actual_delivery_days_sum)
        / nullif(sum(eligible_delivery_order_count), 0) as avg_actual_delivery_days,
    sum(ordered_item_value) as ordered_item_value
from gold.dashboard_order_daily
where purchase_date_key between 20180101 and 20180131;
```

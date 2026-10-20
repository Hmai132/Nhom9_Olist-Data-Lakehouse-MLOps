# Silver models

Run the Bronze loader first, then run dbt from the project root:

```powershell
.venv\Scripts\python.exe -m pipeline.bronze
.venv\Scripts\dbt.exe run --project-dir warehouse --profiles-dir warehouse
.venv\Scripts\dbt.exe test --project-dir warehouse --profiles-dir warehouse
```

The nine `stg_*` models retain the source row counts while converting types,
normalizing identifiers and adding anomaly flags. The tenth model,
`geolocation_by_zip`, provides one representative coordinate per ZIP prefix.
It removes exact duplicate valid coordinate rows before taking the median and
keeps counts of excluded out-of-bounds rows and conflicting place labels.

dbt generic tests check required values, unique keys, accepted categories and
relationships. Singular tests check composite keys, Bronze-to-Silver row counts
and representative coordinate bounds. Expected Olist anomalies are flagged,
not silently deleted or treated as test failures.

This profile targets the local DuckDB file. MotherDuck credentials and remote
deployment are intentionally separate from these local model definitions.

# Gold models

Run all Gold models and their tests after Silver:

```powershell
.venv\Scripts\dbt.exe run --project-dir warehouse --profiles-dir warehouse --select path:models/gold
.venv\Scripts\dbt.exe test --project-dir warehouse --profiles-dir warehouse --select path:models/gold path:tests/gold_fact_order_grain.sql path:tests/gold_item_totals.sql path:tests/gold_ml_labels.sql
```

`fact_delivery_performance` has one row per order. `fact_order_item` has one
row per order item and carries seller/product keys, so item-level joins cannot
silently multiply order-level delivery measures. `dim_customer` identifies a
real buyer by `customer_unique_id`; the order-specific delivery location is a
separate geolocation key because a buyer can use different addresses.

`ml_wide_delivery_table` has one row per order, separates `feature_*` from
`target_*`, and omits post-purchase timestamps and reviews from the feature
columns. Historical seller and rolling features, train/test splitting, and
the exact feature availability cutoff belong to the next ML stage. In
particular, using the promised delivery date at purchase time is an explicit
assumption to validate before training.

`dim_date` covers all order milestones plus item shipping limits. A few source
shipping limits extend into 2020; they are retained and can be investigated
without breaking referential integrity.

# Gold dashboard metric marts

Build and check the dashboard tables after the core Gold models:

```powershell
.venv\Scripts\dbt.exe run --project-dir warehouse --profiles-dir warehouse --select dashboard_order_base dashboard_order_daily dashboard_category_daily dashboard_seller_daily dashboard_customer_order_base
.venv\Scripts\dbt.exe test --project-dir warehouse --profiles-dir warehouse --select dashboard_order_base dashboard_order_daily dashboard_category_daily dashboard_seller_daily dashboard_customer_order_base dashboard_order_reconciliation dashboard_category_reconciliation dashboard_seller_reconciliation dashboard_customer_reconciliation
```

`dashboard_order_base` has one row per order and carries the exact customer's
state from the order's customer record, plus purchase weekday, order item-line
count band, promised-delivery-window band and nullable milestone durations for
descriptive slicing. The diagnostic page keeps this one-order grain and uses
stage-specific non-null denominators when comparing late and on-time orders.
`dashboard_order_daily` has one row per
purchase date, customer state and order status. `dashboard_category_daily`
aggregates item-grain prices by purchase date, customer state, order status
and category. `dashboard_seller_daily` uses purchase date, customer state,
order status and seller grain for additive item measures. The one-order
`dashboard_customer_order_base` classifies a buyer's first observed order
and later orders across the full extract before any dashboard filter.
The dbt reconciliation tests compare counts and totals back to both Gold fact
tables and check each mart's grain. See [dashboard_metrics.md](dashboard_metrics.md)
for the metric definitions, month-over-month comparison, filter/date-role
contract, and SQL/DAX examples.
These tables contain actual historical measures, not ML prediction outputs.

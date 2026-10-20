# Olist dashboard (local)

Run from the project root after the Gold dashboard marts have been built:

```powershell
.venv\Scripts\python.exe -m dashboard.server
```

Open `http://127.0.0.1:8501` in a browser. The server binds only to the
local computer and opens `data/warehouse/olist.duckdb` read-only for each
request. Refresh the browser after rebuilding the Gold marts to see new data;
restart the server after changing `server.py`.
The dashboard has five views: **Tổng quan** for six monthly KPIs and MoM
(orders, ordered item value, item value per order, late orders, late rate, and
mean review score), a switchable 12-month trend, a customer-state late-rate
comparison, and the top five categories plus all remaining item value,
**Chẩn đoán giao trễ** for stage-time comparisons, a cross-dimension
late-rate matrix and switchable breakdowns, and
**Sản phẩm & người bán** for all-category ranking and search, category trends,
seller concentration, and seller-state distribution, and **Khách hàng & đánh giá**
shows distinct buyers, previously observed buyers, review coverage and low
review share, monthly trends, first/subsequent order groups, and review
comparisons for late versus on-time delivered orders. **Dự đoán giao hàng** is
the last tab; it turns both predicted delivery days and late-delivery risk
scores into a retrospective manager view for the same July–August 2018 test
orders. It shows simulated manual calls, automated reminders, weekly workload,
state concentrations, and a prioritized order queue. The upper-right
filter panel applies to the four historical-actuals views. The prediction tab
has its own month, customer-state, and exact order-ID filters.

KPI cards stay on one row and scroll horizontally on narrower screens. The
month-over-month border and arrow show change direction, not whether the
change is good for the business. Month arrows and trend charts change the
active month. State and status filter chips can be removed individually.
State rows drill into delivery analysis, overview categories open the product
view, and order IDs open details for both ML outputs.

Build the prediction export after the existing ML artifacts have been produced:

```powershell
.venv\Scripts\python.exe -m pipeline.dashboard_prediction_export
```

This writes `data/ml/models/dashboard_joint_predictions.csv` and its metadata.
Run `python -m pipeline.save_predictions_to_gold` afterward. The prediction
tab reads `gold.fact_delivery_predictions` from DuckDB; the CSV is only the
export used to populate that table. Re-run the sync after rebuilding the
prediction export.
The export deliberately excludes actual labels and delivery outcomes. It joins
the existing label-free operational scenario decisions by order ID; the
scenario ranks scores within completed eight-hour shifts and applies the
existing manual-call quota. Filtering month or state does not re-rank those
historical decisions. The
regression model's displayed test predictions have no test error metric; its
shown MAE comes from May–June validation. Negative predicted days are marked
invalid and excluded from the displayed mean. The logistic model's score is
not a calibrated probability. Its frozen score threshold and ROC AUC/AP are
from the one-time July–August test and do not change with dashboard filters.
The dashboard is a retrospective demonstration, not live scoring for new
orders. Its test cohort contains only orders whose labels eventually became
available.

The default date role is **purchase date**. The selected calendar month is
compared with its preceding calendar month under the same customer-state and
order-status filters. The default is the latest month whose source orders
cover both the first and last calendar day (August 2018 in this extract).
Other months remain selectable and are marked as partial when the observed
purchase dates do not span the full month. Partial-month MoM uses the full
previous month and must be interpreted cautiously. Rates are calculated from
filtered numerator and denominator sums. The breakdown selector offers state,
status, order-size band, promised-window band, and purchase weekday. The
displayed value is ordered item price, not recognized revenue or net sales. See
`warehouse/dashboard_metrics.md` for the full business definitions.

The Overview layout also draws on *Ecommerce Analytics* by Judah Phillips in
NotebookLM: it links commercial scale and mix with fulfillment and customer
feedback. These Olist files start at orders, so the dashboard does not infer
traffic, conversion, acquisition cost, margin, or refunds. Gold order and item
facts are aggregated separately to avoid multiplying order values across item
lines. The original Data Warehouse and Power BI notebooks remain the project
references for grain, measures, and reporting behavior.

The diagnostic view uses only eligible delivered orders for late/on-time stage
comparisons. Each stage average uses its own count of valid non-null milestone
durations. The matrix crosses customer state, item-line-count band, or purchase
weekday with the promised-delivery-window band; each cell displays its eligible
denominator. Highlight cards require at least 20 eligible orders and 1% of the
filtered cohort. These are historical associations, not causal findings.

The product and seller page uses the item-grain Gold marts. It shows item
value, item lines, active categories, and active sellers with prior-month
comparisons. The category table covers every category in the selected month;
its order count means orders *containing that category* and cannot be summed
across categories. The top-eight display also includes a remainder group.
Seller ranking (identified by seller city, state and short ID) and seller-state
distribution use `dashboard_seller_daily`;
top-ten concentration is a share of all filtered item value. Seller-state
refers to the seller's registered state, while the global state filter refers
to the customer's state. Order-level delivery and review outcomes are not
attributed to sellers because some orders contain multiple sellers.

Customer identity uses `customer_unique_id` via the Gold customer key, not the
order-specific `customer_id`. "Previously observed buyer" means the buyer's
first order in the full extract predates the selected month. A subsequent
order is order number 2 or later in that same observed history. Neither is a
retention or churn measure: the extract begins and ends at finite dates, and
recent buyers have less time to place another order. Review coverage is
reviewed delivered-status orders / delivered-status orders. Mean review score
and low-review share (order mean score at most 2) use only orders with a
non-null review. The late/on-time review comparison includes only delivered
orders with valid delivery and promise dates and is descriptive, not causal.

Check the dashboard query contract with:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_dashboard_api -v
```

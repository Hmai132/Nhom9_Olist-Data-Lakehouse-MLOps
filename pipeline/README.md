# Bronze ingestion

The final reporting steps are `python -m pipeline.explainability` and
`python -m pipeline.save_predictions_to_gold`, after the historical model,
operational policy and dashboard prediction export have been built. XAI saves
Beeswarm and red-order Waterfall figures in `outputs/figures/chapter4/` and
positive log-odds SHAP drivers for each test order in
`data/ml/models/xai_top3_delay_reasons.csv`. The Gold sync stores label-free
predictions in `gold.fact_delivery_predictions`; the dashboard prediction tab
reads that table. These results describe a retrospective test cohort, not live
scoring of new orders.

From the project root, install `requirements.txt` in a Python 3.11 virtual
environment and run:

```powershell
.venv\Scripts\python.exe -m pipeline.bronze
```

The default output is `data/warehouse/olist.duckdb`. The nine `bronze` views
expose the current CSV version. `bronze_snapshots` retains each version under
its full SHA-256 hash, while `bronze.ingestion_manifest` records the source
file, hash, byte count, row count, ingestion time and current version. Running
the command again with unchanged CSVs reuses the snapshots.

Use `--raw-dir` and `--database` to override paths. This step runs locally;
MotherDuck connectivity is a later deployment configuration.

# ML dataset preparation

After the dbt Gold models and tests pass, run:

```powershell
.venv\Scripts\python.exe -m pipeline.ml_dataset
```

The command exports `data/ml/train.parquet`, `validation.parquet`,
`test.parquet` and `manifest.json`. The splits use purchase time, with
validation starting 2018-05-01 and test starting 2018-07-01. They retain all
eligible labeled orders in each purchase cohort. The manifest reports how
many labels arrived after the next split began; this retrospective split is
not yet a historical deployment replay. A deployment replay requires a
separate label-maturity design before fitting models.

Features are an explicit allowlist at the purchase-time cutoff. The promised
delivery interval is included because the project owner confirmed that the
estimated delivery date is available when the order is placed.
Post-purchase milestones, order status and reviews are never exported as
features. Both timestamp-based and calendar-day late labels are retained so
the business definition can be chosen before classifier training. Missing
feature values remain missing; fit any imputer or encoder on train only.

# Historical label availability

After preparing the ML cohorts, run:

```powershell
.venv\Scripts\python.exe -m pipeline.label_availability
```

This exports `data/ml/train_asof_validation.parquet` and
`label_availability.json`. The default 90-day maturity gap allows only orders
purchased before 2018-01-31 into the training candidate set. A label enters
training only if the order was delivered before validation began on 2018-05-01.
The report compares several gap lengths and documents label coverage. This
prepares an as-of training cohort; it does not train or evaluate a model.
Validation remains the complete May-June purchase cohort and the test set stays
untouched. The Gold extract is static, so historical feature versions cannot be
verified from these files.

# Feature audit

Before fitting models, audit the purchase-time features:

```powershell
.venv\Scripts\python.exe -m pipeline.feature_audit
```

`data/ml/feature_audit.json` records train-only distributions, missingness,
skew and descriptive association with the delay label. It checks unlabeled
validation missingness and unseen categories without opening the test cohort.
The audit found strong right skew in item price, freight and weight, so the
classification preprocessing applies `log1p` to those three nonnegative
features inside its train-fitted pipeline. The linear regression baseline keeps
their raw values because the transformation worsened validation MAE and RMSE.
This validation comparison is exploratory until the historical validation
timeline is corrected.

# Regression baseline

After preparing the ML cohorts and the as-of training cohort, run:

```powershell
.venv\Scripts\python.exe -m pipeline.regression_baseline
```

This fits a scikit-learn `LinearRegression` pipeline on the May 1 as-of train
cohort, evaluates MAE, RMSE and R2 on validation, and saves the fitted model,
predictions and metrics with `regression_asof_*` names under `data/ml/models/`.
A train-median benchmark is reported for context. The test cohort is untouched.
The static Gold extract does not provide historical feature versions.

# Classification baseline

After preparing the as-of training cohort, run:

```powershell
.venv\Scripts\python.exe -m pipeline.classification_baseline
```

This fits a train-only preprocessing pipeline with class-weighted logistic
regression for calendar-day delivery delay. A majority-class dummy is the
benchmark. The default 0.5 threshold is used without tuning. Accuracy,
precision, recall, F1, ROC AUC and the confusion matrix are reported on the
May-June validation cohort under `data/ml/models/classification_asof_*`.
The test cohort remains untouched.

# Classifier comparison by alert capacity

After the logistic baseline, run:

```powershell
.venv\Scripts\python.exe -m pipeline.classification_compare
```

The command compares the saved logistic baseline with fixed-parameter
Random Forest and LightGBM pipelines on the same as-of train and validation
cohorts. It reports ROC AUC and precision/recall for the highest-scored 5%,
10% and 20% of validation orders. The 10% budget selects a provisional model
on validation. Scores from class-weighted models are used for ranking, not
treated as calibrated delivery-delay probabilities. The test set stays sealed.

# Historical model and threshold selection

After the exploratory comparison, run:

```powershell
.venv\Scripts\python.exe -m pipeline.historical_selection
```

This rebuilds a 90-day-matured training cohort as it stood on 2018-03-01,
scores March-April orders, and selects among logistic regression, Random
Forest and LightGBM using only delivery labels known by 2018-07-01. The
March-April validation has 13,801 orders; five labels were still unknown on
the decision date and are masked in the exported validation file. A score
threshold is fixed from all validation scores to target at most 10% alerts
there; 5% and 20% are sensitivity checks. The selected model and threshold
are frozen for the next test stage. The fixed threshold can be applied as
each order arrives, but a future cohort may exceed 10% alerts if scores drift.
The test cohort remains unopened. Earlier May-June validation was used during
exploratory feature engineering, so this revised protocol is not a fully
untouched prospective study. Static Gold features are not versioned by
purchase time, and the source cohort contains only eventually label-eligible
delivered orders.

# One-time frozen test evaluation

Run only after `historical_selection_metrics.json` and the selected model are
frozen:

```powershell
.venv\Scripts\python.exe -m pipeline.historical_test
```

The command evaluates the selected model on the July-August test cohort using
the score thresholds fixed on March-April validation. It saves predictions and
metrics under `data/ml/models/historical_test_*`. It refuses to overwrite an
existing test result and records hashes of the frozen selection, model and
test input. The 10% validation threshold is a target, not a guaranteed cap:
the one-time test produced a 40.9% alert rate. This result is diagnostic and
must not be used to retune the frozen threshold while claiming the same test
as untouched.

# Post-test drift diagnosis

```powershell
.venv\Scripts\python.exe -m pipeline.drift_audit
```

This reads the frozen validation/test predictions and transforms both cohorts
with the already-fitted Logistic Regression pipeline. It records score and
feature distribution changes, monthly alert/late rates, and an exact additive
breakdown of the model's mean log-odds shift by input feature in
`historical_test_drift_audit.json`. It does not refit the model, remove
features, calibrate probabilities, or change the alert threshold. The
breakdown explains the model's score movement; it does not establish what
caused delivery delays. It is a post-test diagnostic, so any redesign based on
it needs a new evaluation period before a fresh unbiased performance claim.

# Exploratory hybrid alert policy

```powershell
.venv\Scripts\python.exe -m pipeline.hybrid_alert_policy
```

`pipeline/alert_policy.json` sets eight-hour shifts, a red top-5% risk band,
yellow through the top 25%, a default manual-call capacity per shift, and
optional per-shift capacity overrides. The example capacity of 500 is an
upper bound, not a target number of calls. Within each shift, orders are
ranked by the frozen model score, with `order_id` breaking ties. Red orders
receive manual calls until capacity is full; excess red and yellow orders
receive automated messages; green orders receive no action. Ranking is
available at the end of each shift, so this simulation does not promise an
instant response at purchase time. The output is a post-test operational
scenario, and historical late labels describe which orders were in each
group; they cannot measure whether an intervention would prevent a delay.

Check ranking, overflow and label isolation with:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_hybrid_alert_policy -v
```

# Exploratory probability calibration

```powershell
.venv\Scripts\python.exe -m pipeline.calibration_experiment
```

This freezes the selected base classifier, fits sigmoid and isotonic
calibrators on March 2018 orders whose labels were known before 2018-07-01,
and compares them with raw scores and a March-prevalence constant on known
April labels. It saves Brier loss, log loss, ranking metrics, assessment
predictions, reliability bins and a PNG reliability diagram in `data/ml/models/`.
The script never reads the July-August test cohort. Because March-April labels
were already used in base-model selection and the test has been opened, this
is an exploratory calibration study, not a new independent evaluation. The
probability-calibration methods are a project extension supported by
scikit-learn documentation; the two course NotebookLM sources do not teach
Platt scaling or isotonic regression directly. Calibration does not enforce
the manual-call capacity configured by the hybrid alert policy.

# Exploratory chronological feature comparison

```powershell
.venv\Scripts\python.exe -m pipeline.temporal_feature_experiment
```

This compares the existing numeric purchase-month feature with dropping the
month, one-hot month encoding, cyclic month encoding, and dropping promised
delivery days. It uses January-April 2018 purchase cohorts from the pre-May
training extract. For each month, the logistic model and all preprocessing are
refitted only on orders purchased at least 90 days earlier whose delivery
labels were known at that month's start. Assessment labels are masked if the
delivery was not known within the next two calendar months. It reports ROC
AUC, average precision, raw-score Brier loss, and the top 5% risk band ranked
within completed eight-hour shifts. July-August cohort files and predictions
are not loaded. Results are in
`data/ml/models/temporal_feature_experiment_metrics.json`; the script refuses
to overwrite them. It does not update the frozen v1 model or alert policy.

The NotebookLM *Python Data Analysis* source supports date-part extraction,
one-hot encoding, train-only preprocessing in a pipeline, and chronological
validation. Cyclic encoding and delayed-label masking are explicit project
extensions. The already-opened test motivated this experiment, so the results
are exploratory and cannot establish a new independent test performance.

# Dashboard prediction export

```powershell
.venv\Scripts\python.exe -m pipeline.dashboard_prediction_export
```

This combines the frozen July–August 2018 classifier test scores with
delivery-day predictions from the purchase-time linear regression model for
the same orders. It writes a label-free CSV and metadata under
`data/ml/models/` for the dashboard. It does not calculate regression error
on the test cohort. The regression validation MAE and classifier one-time
test metrics are identified separately in the metadata.

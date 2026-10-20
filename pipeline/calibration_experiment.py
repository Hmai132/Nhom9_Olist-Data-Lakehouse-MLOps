"""Post-test calibration study using only labels known before 2018-07-01.

The pre-fitted March-April-selected classifier is frozen. March orders fit
sigmoid and isotonic calibrators; April orders assess both against raw scores.
The July-August test file and predictions are never opened by this module.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import MODEL_FEATURES, TARGET
from pipeline.regression_baseline import file_sha256


CALIBRATION_START = pd.Timestamp("2018-03-01")
ASSESSMENT_START = pd.Timestamp("2018-04-01")
ASSESSMENT_END = pd.Timestamp("2018-05-01")
METHODS = ("raw", "sigmoid", "isotonic")


def decile_table(labels: np.ndarray, scores: np.ndarray, method: str) -> pd.DataFrame:
    # Equal-count bins make sparse positive-class calibration easier to inspect.
    ranks = pd.Series(scores).rank(method="first").to_numpy()
    bucket = pd.qcut(ranks, q=10, labels=False, duplicates="drop")
    frame = pd.DataFrame({"bucket": bucket, "label": labels, "score": scores})
    table = frame.groupby("bucket", sort=True).agg(
        orders=("label", "size"), mean_score=("score", "mean"),
        observed_delay_rate=("label", "mean"), min_score=("score", "min"),
        max_score=("score", "max"),
    ).reset_index()
    table.insert(0, "method", method)
    table["decile"] = table["bucket"] + 1
    return table.drop(columns="bucket")


def draw_reliability(bins: pd.DataFrame, output_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=False)
    colors = {"raw": "#7f7f7f", "sigmoid": "#087e8b", "isotonic": "#d95d39"}
    for ax, limit in zip(axes, (1.0, 0.35)):
        ax.plot([0, limit], [0, limit], linestyle="--", color="black", linewidth=1,
                label="perfect calibration")
        for method in METHODS:
            data = bins.loc[bins.method == method]
            ax.plot(data.mean_score, data.observed_delay_rate, marker="o", markersize=4,
                    linewidth=1.6, color=colors[method], label=method)
        ax.set_xlim(0, limit)
        ax.set_ylim(0, limit)
        ax.set_xlabel("Mean predicted score or probability")
        ax.set_ylabel("Observed late fraction")
        ax.set_title("April assessment" + (" (zoom)" if limit < 1 else ""))
        ax.grid(alpha=.25)
    axes[0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Exploratory probability calibration (March fit, April assessment)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def run(model_dir: Path) -> dict:
    selection_path = model_dir / "historical_selection_metrics.json"
    validation_path = model_dir / "historical_validation_masked.parquet"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection["decision_asof"] != "2018-07-01T00:00:00":
        raise ValueError("Expected the pre-July decision snapshot")
    if selection["input_sha256"]["historical_validation_masked"] != file_sha256(validation_path):
        raise ValueError("Masked validation cohort changed since model selection")
    selected = selection["selected_model"]
    model_path = model_dir / f"historical_{selected}.joblib"
    model = joblib.load(model_path)
    # Read only the March-April masked cohort. Unknown labels remain excluded.
    connection = duckdb.connect()
    try:
        frame = connection.read_parquet(str(validation_path)).df()
    finally:
        connection.close()
    if len(frame) != selection["validation_rows"]:
        raise ValueError("Validation cohort row count changed")
    calibration = frame.loc[
        frame.prediction_cutoff_ts.ge(CALIBRATION_START)
        & frame.prediction_cutoff_ts.lt(ASSESSMENT_START)
        & frame[TARGET].notna()
    ].copy()
    assessment = frame.loc[
        frame.prediction_cutoff_ts.ge(ASSESSMENT_START)
        & frame.prediction_cutoff_ts.lt(ASSESSMENT_END)
        & frame[TARGET].notna()
    ].copy()
    if not len(calibration) or not len(assessment):
        raise ValueError("Both March and April need known labels")
    if set(calibration.order_id).intersection(assessment.order_id):
        raise ValueError("Calibration and assessment orders overlap")
    # The frozen base model was trained on purchases before 2017-12-01.
    if pd.Timestamp(selection["train_purchase_before"]) >= CALIBRATION_START:
        raise ValueError("Calibration orders overlap the base model training era")
    x_cal = calibration.loc[:, MODEL_FEATURES]
    y_cal = calibration[TARGET].to_numpy(dtype=int)
    x_assess = assessment.loc[:, MODEL_FEATURES]
    y_assess = assessment[TARGET].to_numpy(dtype=int)
    if set(np.unique(y_cal)) != {0, 1} or set(np.unique(y_assess)) != {0, 1}:
        raise ValueError("Each calibration period requires both label classes")

    scores = {
        "raw": model.predict_proba(x_assess)[:, 1],
        "march_prevalence": np.full(len(assessment), float(y_cal.mean())),
    }
    saved_validation_path = model_dir / "historical_validation_predictions.csv"
    saved_validation = pd.read_csv(saved_validation_path)
    if not saved_validation.order_id.equals(frame.order_id):
        raise ValueError("Saved validation scores do not align to the masked cohort")
    expected_raw = saved_validation.loc[assessment.index, f"{selected}_score"].to_numpy()
    if not np.allclose(scores["raw"], expected_raw):
        raise ValueError("Frozen base model disagrees with saved April scores")
    calibrator_paths = {}
    for method in ("sigmoid", "isotonic"):
        calibrator = CalibratedClassifierCV(
            estimator=FrozenEstimator(model), method=method
        )
        calibrator.fit(x_cal, y_cal)
        scores[method] = calibrator.predict_proba(x_assess)[:, 1]
        path = model_dir / f"calibration_{method}_march.joblib"
        joblib.dump(calibrator, path)
        calibrator_paths[method] = path.name

    metrics = {}
    bins = []
    predictions = pd.DataFrame({
        "order_id": assessment.order_id,
        "prediction_cutoff_ts": assessment.prediction_cutoff_ts,
        "actual_is_delayed_calendar_day": y_assess,
    })
    for method, probability in scores.items():
        if not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
            raise ValueError(f"Invalid {method} assessment scores")
        predictions[f"{method}_score"] = probability
        metrics[method] = {
            "brier_loss": float(brier_score_loss(y_assess, probability)),
            "log_loss": float(log_loss(y_assess, probability, labels=[0, 1])),
            "roc_auc": float(roc_auc_score(y_assess, probability)),
            "average_precision": float(average_precision_score(y_assess, probability)),
            "mean_predicted": float(probability.mean()),
        }
        if method in METHODS:
            bins.append(decile_table(y_assess, probability, method))
    bins_frame = pd.concat(bins, ignore_index=True)
    prediction_path = model_dir / "calibration_april_predictions.csv"
    bins_path = model_dir / "calibration_april_reliability_bins.csv"
    figure_path = model_dir / "calibration_april_reliability.png"
    predictions.to_csv(prediction_path, index=False)
    bins_frame.to_csv(bins_path, index=False)
    draw_reliability(bins_frame, figure_path)

    result = {
        "scope": "post-test exploratory calibration of a frozen model; no July-August test access",
        "selected_base_model": selected,
        "calibration_month": "2018-03",
        "assessment_month": "2018-04",
        "calibration_rows_known": len(calibration),
        "calibration_late": int(y_cal.sum()),
        "calibration_prevalence": float(y_cal.mean()),
        "assessment_rows_known": len(assessment),
        "assessment_late": int(y_assess.sum()),
        "assessment_prevalence": float(y_assess.mean()),
        "metrics": metrics,
        "no_test_fit_or_tuning": True,
        "selection_caveat": "The base classifier was previously selected using March-April outcomes. April calibration assessment is therefore exploratory, not an untouched validation for the full modeling process.",
        "transfer_caveat": "March and April have different delay prevalence; lower Brier/log loss in April would not prove stable calibration in July-August.",
        "operational_caveat": "Calibration does not impose manual-call quota or guarantee alert-volume fractions.",
        "input_sha256": {
            "selection_metrics": file_sha256(selection_path),
            "frozen_model": file_sha256(model_path),
            "historical_validation_masked": file_sha256(validation_path),
            "historical_validation_predictions": file_sha256(saved_validation_path),
        },
        "package_versions": {"scikit_learn": sklearn.__version__,
                             "matplotlib": matplotlib.__version__, "numpy": np.__version__,
                             "pandas": pd.__version__},
        "files": {
            "calibrators": calibrator_paths,
            "assessment_predictions": prediction_path.name,
            "reliability_bins": bins_path.name,
            "reliability_figure": figure_path.name,
        },
    }
    (model_dir / "calibration_experiment_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    args = parser.parse_args()
    result = run(args.model_dir)
    print(json.dumps({key: result[key] for key in (
        "calibration_rows_known", "calibration_prevalence",
        "assessment_rows_known", "assessment_prevalence", "metrics",
        "no_test_fit_or_tuning",
    )}, indent=2))


if __name__ == "__main__":
    main()

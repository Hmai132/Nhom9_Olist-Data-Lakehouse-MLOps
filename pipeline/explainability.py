"""Explain the frozen delay classifier with SHAP and export order-level drivers.

The values explain the classifier's log-odds score, not a calibrated risk
probability or a causal effect. No test labels are used in the explanation.
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
import shap

from pipeline.bronze import PROJECT_ROOT
from pipeline.classification_baseline import MODEL_FEATURES


def run_xai(data_dir: Path, model_dir: Path, figure_dir: Path) -> dict:
    selection = json.loads((model_dir / "historical_selection_metrics.json").read_text(encoding="utf-8"))
    if selection["selected_model"] != "logistic_regression":
        raise ValueError("Linear SHAP requires the frozen logistic regression model")
    model = joblib.load(model_dir / "historical_logistic_regression.joblib")
    preprocessor = model.named_steps["preprocessing"]
    classifier = model.named_steps["classifier"]

    connection = duckdb.connect()
    try:
        orders = connection.read_parquet(str(data_dir / "test.parquet")).project(
            ", ".join(f'"{column}"' for column in ("order_id", *MODEL_FEATURES))
        ).df()
    finally:
        connection.close()
    if orders.empty or orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError("Test orders must have unique, nonnull IDs")

    decisions = pd.read_csv(
        model_dir / "hybrid_policy_test_exploratory_decisions.csv",
        usecols=["order_id", "risk_zone", "delay_score"],
    )
    if decisions.order_id.isna().any() or decisions.order_id.duplicated().any():
        raise ValueError("Policy decisions must have unique, nonnull order IDs")
    if set(decisions.order_id) != set(orders.order_id):
        raise ValueError("Policy decisions and test orders do not cover the same IDs")

    transformed = np.asarray(preprocessor.transform(orders.loc[:, MODEL_FEATURES]))
    names = [name.removeprefix("numeric__").removeprefix("log_numeric__")
             .removeprefix("categorical__").removeprefix("feature_")
             for name in preprocessor.get_feature_names_out()]
    if transformed.shape[1] != len(names):
        raise ValueError("Transformed feature names do not match model inputs")
    rng = np.random.default_rng(42)
    sample_indices = rng.choice(len(orders), size=min(1000, len(orders)), replace=False)
    background = transformed[sample_indices]
    explainer = shap.LinearExplainer(classifier, background, feature_names=names)
    sample_values = explainer(background)

    figure_dir.mkdir(parents=True, exist_ok=True)
    shap.plots.beeswarm(sample_values, max_display=12, show=False)
    plt.title("SHAP: tác động của đặc trưng lên rủi ro giao trễ")
    plt.tight_layout()
    beeswarm_path = figure_dir / "hinh_4_xai_shap_beeswarm.png"
    plt.savefig(beeswarm_path, dpi=300, bbox_inches="tight")
    plt.close()

    red = decisions.loc[decisions.risk_zone.eq("red")].sort_values(
        ["delay_score", "order_id"], ascending=[False, True]
    )
    waterfall_path = None
    if not red.empty:
        order_id = red.iloc[0].order_id
        order_position = int(np.flatnonzero(orders.order_id.eq(order_id).to_numpy())[0])
        one = explainer(transformed[order_position:order_position + 1])
        shap.plots.waterfall(one[0], max_display=8, show=False)
        plt.title(f"SHAP: đơn {order_id[:8]}… (vùng Đỏ)")
        plt.tight_layout()
        waterfall_path = figure_dir / "hinh_4_xai_shap_waterfall_red.png"
        plt.savefig(waterfall_path, dpi=300, bbox_inches="tight")
        plt.close()

    # Positive SHAP values raise log-odds of delay. Select only positive
    # contributions, leaving a blank reason when fewer than three exist.
    rows = []
    for start in range(0, len(orders), 1000):
        stop = min(start + 1000, len(orders))
        values = explainer(transformed[start:stop]).values
        for offset, effects in enumerate(values):
            positive = np.flatnonzero(effects > 0)
            top = positive[np.argsort(-effects[positive], kind="stable")[:3]]
            row = {"order_id": orders.iloc[start + offset].order_id}
            for rank in range(3):
                row[f"reason_{rank + 1}"] = names[top[rank]] if rank < len(top) else ""
                row[f"shap_log_odds_{rank + 1}"] = float(effects[top[rank]]) if rank < len(top) else np.nan
            rows.append(row)
    reasons_path = model_dir / "xai_top3_delay_reasons.csv"
    pd.DataFrame(rows).to_csv(reasons_path, index=False)
    return {"orders": len(orders), "red_orders": len(red),
            "beeswarm": str(beeswarm_path), "waterfall": str(waterfall_path) if waterfall_path else None,
            "top3_reasons": str(reasons_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/ml")
    parser.add_argument("--model-dir", type=Path, default=PROJECT_ROOT / "data/ml/models")
    parser.add_argument("--figure-dir", type=Path, default=PROJECT_ROOT / "outputs/figures/chapter4")
    args = parser.parse_args()
    print(json.dumps(run_xai(args.data_dir, args.model_dir, args.figure_dir), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

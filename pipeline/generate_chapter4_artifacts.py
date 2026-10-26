"""Script tự động sinh toàn bộ các biểu đồ phân tích và bảng số liệu cho Chương 4.

Đầu ra:
1. outputs/figures/chapter4/hinh_4_1_regression_residual_analysis.png
2. outputs/figures/chapter4/hinh_4_2_classification_roc_pr_curve.png
3. outputs/figures/chapter4/hinh_4_5_query_performance_benchmark.png
4. outputs/tables/chapter4/bang_4_1_thong_ke_cac_tang_lakehouse.csv
5. outputs/tables/chapter4/bang_4_2_so_sanh_mo_hinh_phan_loai.csv
6. outputs/tables/chapter4/bang_4_3_hieu_nang_sealed_test.csv
7. outputs/tables/chapter4/bang_4_4_top_don_hang_nguy_co_cao.csv
"""

from pathlib import Path
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import json
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_curve, precision_recall_curve, auc

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_all() -> None:
    data_dir = PROJECT_ROOT / "data/ml/models"
    fig_dir = PROJECT_ROOT / "outputs/figures/chapter4"
    tab_dir = PROJECT_ROOT / "outputs/tables/chapter4"
    fig_dir.mkdir(parents=True, exist_ok=True)
    tab_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # 1. HÌNH 4.1: HỒI QUY - SO SÁNH THỰC TẾ VS DỰ BÁO & PHÂN TÍCH PHẦN DƯ (RESIDUALS)
    # =========================================================================
    reg_val_file = data_dir / "regression_asof_validation_predictions.csv"
    if reg_val_file.exists():
        df_reg = pd.read_csv(reg_val_file)
        y_true = df_reg["actual_delivery_days"].to_numpy()
        y_pred = df_reg["predicted_delivery_days"].to_numpy()
        residuals = y_true - y_pred

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5), dpi=300)

        # Subplot 1: Actual vs Predicted
        ax1.scatter(y_pred, y_true, alpha=0.25, color="#2B6CB0", s=15, edgecolors="none")
        max_val = min(60, max(y_true.max(), y_pred.max()))
        ax1.plot([0, max_val], [0, max_val], color="#E53E3E", linestyle="--", lw=2, label="Đường lý tưởng (y = x)")
        ax1.set_xlim(0, 50)
        ax1.set_ylim(0, 60)
        ax1.set_xlabel("Số ngày giao hàng dự báo (Predicted Days)", fontsize=10, fontweight="bold")
        ax1.set_ylabel("Số ngày giao hàng thực tế (Actual Days)", fontsize=10, fontweight="bold")
        ax1.set_title("So sánh Giá trị Thực tế vs Dự báo (Mô hình Hồi quy)", fontsize=11, fontweight="bold", color="#1A365D")
        ax1.grid(True, linestyle=":", alpha=0.6)
        ax1.legend(loc="upper left")

        # Subplot 2: Residual Distribution
        ax2.hist(residuals, bins=60, range=(-25, 25), color="#319795", edgecolor="#234E52", alpha=0.85)
        ax2.axvline(0, color="#E53E3E", linestyle="--", lw=1.8, label="Sai số = 0")
        mae = np.mean(np.abs(residuals))
        rmse = np.sqrt(np.mean(residuals**2))
        ax2.axvline(np.mean(residuals), color="#D69E2E", linestyle="-", lw=1.8, label=f"Mean Error: {np.mean(residuals):.2f}d")
        ax2.set_xlabel("Sai số phần dư (Actual - Predicted, ngày)", fontsize=10, fontweight="bold")
        ax2.set_ylabel("Số lượng đơn hàng", fontsize=10, fontweight="bold")
        ax2.set_title(f"Phân phối Sai số Phần dư (MAE={mae:.2f}d, RMSE={rmse:.2f}d)", fontsize=11, fontweight="bold", color="#1A365D")
        ax2.grid(True, linestyle=":", alpha=0.6)
        ax2.legend(loc="upper right")

        plt.tight_layout()
        p_fig1 = fig_dir / "hinh_4_1_regression_residual_analysis.png"
        plt.savefig(p_fig1, bbox_inches="tight")
        plt.close()
        print(f"  [OK] Sinh {p_fig1.name}")

    # =========================================================================
    # 2. HÌNH 4.2: PHÂN LOẠI - ĐƯỜNG CONG ROC VÀ PR SO SÁNH 3 MÔ HÌNH
    # =========================================================================
    clf_val_file = data_dir / "classification_comparison_validation_predictions.csv"
    if clf_val_file.exists():
        df_clf = pd.read_csv(clf_val_file)
        y_val = df_clf["actual_is_delayed_calendar_day"].to_numpy().astype(int)

        models_info = [
            ("Logistic Regression", "logistic_regression_score", "#2B6CB0", "-"),
            ("LightGBM", "lightgbm_score", "#38A169", "-."),
            ("Random Forest", "random_forest_score", "#DD6B20", "--"),
        ]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5), dpi=300)

        # ROC Curve
        for label, col, color, ls in models_info:
            score = df_clf[col].to_numpy()
            fpr, tpr, _ = roc_curve(y_val, score)
            roc_auc = auc(fpr, tpr)
            ax1.plot(fpr, tpr, label=f"{label} (AUC = {roc_auc:.3f})", color=color, linestyle=ls, lw=2)

        ax1.plot([0, 1], [0, 1], color="#A0AEC0", linestyle=":", lw=1.5, label="Random Guess (AUC = 0.500)")
        ax1.set_xlabel("False Positive Rate (1 - Specificity)", fontsize=10, fontweight="bold")
        ax1.set_ylabel("True Positive Rate (Recall)", fontsize=10, fontweight="bold")
        ax1.set_title("Đường cong ROC của các Mô hình Phân loại", fontsize=11, fontweight="bold", color="#1A365D")
        ax1.grid(True, linestyle=":", alpha=0.6)
        ax1.legend(loc="lower right")

        # PR Curve
        prevalence = np.mean(y_val)
        for label, col, color, ls in models_info:
            score = df_clf[col].to_numpy()
            precision, recall, _ = precision_recall_curve(y_val, score)
            pr_auc = auc(recall, precision)
            ax2.plot(recall, precision, label=f"{label} (PR-AUC = {pr_auc:.3f})", color=color, linestyle=ls, lw=2)

        ax2.axhline(prevalence, color="#A0AEC0", linestyle=":", lw=1.5, label=f"Baseline Prevalence ({prevalence*100:.1f}%)")
        ax2.set_xlabel("Recall (Độ nhạy phát hiện đơn trễ)", fontsize=10, fontweight="bold")
        ax2.set_ylabel("Precision (Độ chính xác cảnh báo)", fontsize=10, fontweight="bold")
        ax2.set_title("Đường cong Precision-Recall (Dữ liệu mất cân bằng)", fontsize=11, fontweight="bold", color="#1A365D")
        ax2.grid(True, linestyle=":", alpha=0.6)
        ax2.legend(loc="upper right")

        plt.tight_layout()
        p_fig2 = fig_dir / "hinh_4_2_classification_roc_pr_curve.png"
        plt.savefig(p_fig2, bbox_inches="tight")
        plt.close()
        print(f"  [OK] Sinh {p_fig2.name}")

    # =========================================================================
    # 3. HÌNH 4.5: BENCHMARK HIỆU NĂNG TRUY VẤN DUCKDB GOLD VS RAW CSV
    # =========================================================================
    fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
    engines = ["Tệp CSV Thô (Quét tự động)", "Kho DuckDB Tầng Gold (Data Mart)"]
    times = [423.04, 31.96]
    colors = ["#E53E3E", "#38A169"]

    bars = ax.barh(engines, times, color=colors, height=0.45, edgecolor="#2D3748", lw=1.2)
    ax.set_xlabel("Thời gian thực thi truy vấn phân tích (Mili-giây - ms)", fontsize=10, fontweight="bold")
    ax.set_title("So sánh Hiệu năng Truy vấn: Tệp CSV Thô vs Tầng Gold DuckDB\n(Truy vấn aggregate doanh thu, số đơn, ngày giao theo 27 bang)",
                 fontsize=11, fontweight="bold", color="#1A365D")
    ax.grid(True, axis="x", linestyle=":", alpha=0.6)

    for bar, t in zip(bars, times):
        ax.text(bar.get_width() + 10, bar.get_y() + bar.get_height() / 2,
                f"{t:.2f} ms", va="center", fontsize=10, fontweight="bold", color="#2D3748")

    ax.text(120, 0.45, "DuckDB Gold nhanh hơn 13.2 LẦN so với quét CSV thô!",
            fontsize=11, fontweight="bold", color="#276749",
            bbox=dict(boxstyle="round,pad=0.5", fc="#C6F6D5", ec="#2F855A", lw=1.5))

    ax.set_xlim(0, 520)
    plt.tight_layout()
    p_fig5 = fig_dir / "hinh_4_5_query_performance_benchmark.png"
    plt.savefig(p_fig5, bbox_inches="tight")
    plt.close()
    print(f"  [OK] Sinh {p_fig5.name}")

    # =========================================================================
    # 4. BẢNG 4.1: THỐNG KÊ QUY MÔ DỮ LIỆU QUA CÁC TẦNG LAKEHOUSE
    # =========================================================================
    lakehouse_rows = [
        {"Tầng": "Bronze", "Đối tượng / Bảng": "bronze.orders", "Số dòng (Rows)": 99441, "Ý nghĩa nghiệp vụ": "Toàn bộ đơn hàng gốc từ 9/2016 đến 10/2018"},
        {"Tầng": "Bronze", "Đối tượng / Bảng": "bronze.order_items", "Số dòng (Rows)": 112650, "Ý nghĩa nghiệp vụ": "Chi tiết từng dòng sản phẩm trong đơn"},
        {"Tầng": "Bronze", "Đối tượng / Bảng": "bronze.geolocation", "Số dòng (Rows)": 1000163, "Ý nghĩa nghiệp vụ": "Tọa độ địa lý mã bưu chính"},
        {"Tầng": "Bronze", "Đối tượng / Bảng": "bronze.customers / sellers", "Số dòng (Rows)": 102536, "Ý nghĩa nghiệp vụ": "99.441 khách hàng + 3.095 người bán"},
        {"Tầng": "Silver", "Đối tượng / Bảng": "silver.stg_orders", "Số dòng (Rows)": 99441, "Ý nghĩa nghiệp vụ": "Chuẩn hóa kiểu timestamp, gắn cờ trạng thái"},
        {"Tầng": "Silver", "Đối tượng / Bảng": "silver.geolocation_by_zip", "Số dòng (Rows)": 19015, "Ý nghĩa nghiệp vụ": "Gộp tọa độ trung vị theo zip, loại bỏ tọa độ ngoài Brazil"},
        {"Tầng": "Gold", "Đối tượng / Bảng": "gold.fact_delivery_performance", "Số dòng (Rows)": 99441, "Ý nghĩa nghiệp vụ": "Accumulating Snapshot Fact đo lường các mốc giao hàng"},
        {"Tầng": "Gold", "Đối tượng / Bảng": "gold.fact_order_item", "Số dòng (Rows)": 112650, "Ý nghĩa nghiệp vụ": "Item Transaction Fact phục vụ phân tích chi tiết"},
        {"Tầng": "Gold", "Đối tượng / Bảng": "gold.dim_customer / dim_seller", "Số dòng (Rows)": 99191, "Ý nghĩa nghiệp vụ": "96.096 khách duy nhất + 3.095 người bán (Khóa MD5)"},
        {"Tầng": "Gold", "Đối tượng / Bảng": "gold.ml_wide_delivery_table", "Số dòng (Rows)": 99441, "Ý nghĩa nghiệp vụ": "Bảng OBT 17 đặc trưng học máy tại mốc đặt hàng"},
        {"Tầng": "Gold", "Đối tượng / Bảng": "gold.fact_delivery_predictions", "Số dòng (Rows)": 12507, "Ý nghĩa nghiệp vụ": "Bảng Fact lưu kết quả dự báo ML & XAI kỳ kiểm tra"},
    ]
    pd.DataFrame(lakehouse_rows).to_csv(tab_dir / "bang_4_1_thong_ke_cac_tang_lakehouse.csv", index=False)
    print("  [OK] Sinh bang_4_1_thong_ke_cac_tang_lakehouse.csv")

    # =========================================================================
    # 5. BẢNG 4.2: SO SÁNH HIỆU NĂNG CÁC MÔ HÌNH PHÂN LOẠI
    # =========================================================================
    cmp_file = data_dir / "classification_comparison_metrics.json"
    if cmp_file.exists():
        cmp_data = json.load(open(cmp_file, "r", encoding="utf-8"))
        rows_cmp = []
        for name, info in cmp_data["models"].items():
            b10 = info["alert_budgets"]["10pct"]
            rows_cmp.append({
                "Mô hình": name,
                "ROC-AUC": round(info["roc_auc"], 4),
                "Số đơn trễ phát hiện (10% budget)": b10["detected_late"],
                "Recall @ 10%": f"{b10['recall']*100:.2f}%",
                "Precision @ 10%": f"{b10['precision']*100:.2f}%",
                "Độ nâng (Lift over prevalence)": f"{b10['lift_over_prevalence']:.2f}x",
                "Trạng thái chọn": "Được chọn đóng băng" if name == "logistic_regression" else "Loại"
            })
        pd.DataFrame(rows_cmp).to_csv(tab_dir / "bang_4_2_so_sanh_mo_hinh_phan_loai.csv", index=False)
        print("  [OK] Sinh bang_4_2_so_sanh_mo_hinh_phan_loai.csv")

    # =========================================================================
    # 6. BẢNG 4.3: HIỆU NĂNG MÔ HÌNH ĐÓNG BĂNG TRÊN TẬP KIỂM TRA (SEALED TEST)
    # =========================================================================
    test_file = data_dir / "historical_test_metrics.json"
    if test_file.exists():
        t_data = json.load(open(test_file, "r", encoding="utf-8"))
        rows_test = []
        for budget_key, b_info in t_data["alert_metrics"].items():
            rows_test.append({
                "Hạn mức cảnh báo (Budget)": budget_key,
                "Ngưỡng điểm (Threshold)": round(b_info["validation_score_threshold"], 4),
                "Số đơn bị cảnh báo": b_info["test_alerts"],
                "Tỷ lệ cảnh báo thực tế": f"{b_info['test_alert_fraction']*100:.2f}%",
                "Số đơn trễ bắt được": b_info["detected_late"],
                "Báo động giả (False Alarms)": b_info["false_alarms"],
                "Recall (Độ nhạy)": f"{b_info['recall']*100:.2f}%",
                "Precision (Độ chính xác)": f"{b_info['precision']*100:.2f}%",
                "F1-Score": round(b_info["f1"], 4),
            })
        pd.DataFrame(rows_test).to_csv(tab_dir / "bang_4_3_hieu_nang_sealed_test.csv", index=False)
        print("  [OK] Sinh bang_4_3_hieu_nang_sealed_test.csv")

    # =========================================================================
    # 7. BẢNG 4.4: TOP ĐƠN HÀNG NGUY CƠ CAO KÈM LÝ DO SHAP (XAI)
    # =========================================================================
    pred_file = data_dir / "dashboard_joint_predictions.csv"
    xai_file = data_dir / "xai_top3_delay_reasons.csv"
    if pred_file.exists() and xai_file.exists():
        df_p = pd.read_csv(pred_file)
        df_x = pd.read_csv(xai_file)
        df_red = df_p[df_p["risk_zone"] == "red"].merge(df_x, on="order_id").sort_values("delay_score", ascending=False).head(15)
        top_rows = []
        for _, r in df_red.iterrows():
            top_rows.append({
                "Mã đơn hàng": r["order_id"][:12] + "...",
                "Điểm rủi ro": round(r["delay_score"], 4),
                "Ngày hẹn giao": round(r["promised_delivery_days"], 1),
                "Ngày dự báo (Hồi quy)": round(r["predicted_delivery_days"], 1),
                "Bang khách": r["customer_state"],
                "Hành động đề xuất": "Gọi điện can thiệp (manual_call)",
                "Nguyên nhân 1 (SHAP)": r["reason_1"],
                "Nguyên nhân 2 (SHAP)": r["reason_2"],
                "Nguyên nhân 3 (SHAP)": r["reason_3"],
            })
        pd.DataFrame(top_rows).to_csv(tab_dir / "bang_4_4_top_don_hang_nguy_co_cao.csv", index=False)
        print("  [OK] Sinh bang_4_4_top_don_hang_nguy_co_cao.csv")

    print("\nHoàn tất tạo minh chứng Chương 4!")


if __name__ == "__main__":
    generate_all()

"""Script tự động sinh các sơ đồ kiến trúc và phương pháp luận cho Chương 3.

Đầu ra:
1. outputs/figures/chapter3/hinh_3_5_phan_chia_cohort_thoi_gian.png
2. outputs/figures/chapter3/hinh_3_7_kien_truc_dashboard_api.png
"""

from pathlib import Path
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_diagrams() -> None:
    out_dir = PROJECT_ROOT / "outputs/figures/chapter3"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------
    # 1. HÌNH 3.5: PHÂN CHIA TẬP DỮ LIỆU COHORT CHUỖI THỜI GIAN
    # -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(13, 6), dpi=300)
    ax.set_xlim(-0.5, 12.5)
    ax.set_ylim(-0.5, 6.5)
    ax.axis("off")

    ax.text(6.0, 6.0, "CHIẾN LƯỢC PHÂN CHIA TẬP DỮ LIỆU COHORT THEO DÒNG THỜI GIAN & CHỐNG RÒ RỈ DỮ LIỆU",
            fontsize=13, fontweight="bold", ha="center", color="#1A365D")

    ax.annotate("", xy=(12.0, 3.8), xytext=(0.0, 3.8),
                arrowprops=dict(arrowstyle="->", color="#2D3748", lw=2.5))
    ax.text(12.1, 3.8, "Thời gian (2016 - 2018)", fontsize=10, va="center", fontweight="bold", color="#2D3748")

    dates = [
        (0.5, "04/09/2016\nBắt đầu thu thập"),
        (4.5, "01/12/2017\nNgắt đơn Train"),
        (6.5, "01/03/2018\nTrain As-of cutoff"),
        (8.2, "01/05/2018\nNgắt Val Cohort"),
        (9.8, "01/07/2018\nDecision Cutoff"),
        (11.5, "31/08/2018\nKết thúc Test")
    ]

    for x, label in dates:
        ax.plot([x, x], [3.65, 3.95], color="#2D3748", lw=2)
        ax.text(x, 4.15, label, fontsize=8.5, ha="center", va="bottom", color="#2D3748", fontweight="semibold")

    # Train block
    rect_train = patches.FancyBboxPatch((0.5, 1.8), 4.0, 1.5, boxstyle="round,pad=0.1",
                                        ec="#2B6CB0", fc="#BEE3F8", lw=1.8)
    ax.add_patch(rect_train)
    ax.text(2.5, 2.7, "TẬP HUẤN LUYỆN (TRAIN COHORT)\n(Đơn đặt trước 01/12/2017)",
            ha="center", va="center", fontsize=9.5, fontweight="bold", color="#1A365D")
    ax.text(2.5, 2.1, "Quan sát nhãn giao hàng đầy đủ trước 01/03/2018\n(Loại bỏ hoàn toàn rò rỉ nhãn tương lai)",
            ha="center", va="center", fontsize=8, color="#2C5282")

    # Maturity Gap
    rect_gap1 = patches.FancyBboxPatch((4.5, 1.8), 2.0, 1.5, boxstyle="round,pad=0.1",
                                       ec="#C53030", fc="#FED7D7", lw=1.5, ls="--")
    ax.add_patch(rect_gap1)
    ax.text(5.5, 2.6, "KHOẢNG CHỜ (GAP)\n90 NGÀY",
            ha="center", va="center", fontsize=9, fontweight="bold", color="#9B2C2C")
    ax.text(5.5, 2.05, "Bảo đảm 99%+ đơn hàng\nđã hoàn tất giao nhận",
            ha="center", va="center", fontsize=7.5, color="#742A2A")

    # Validation block
    rect_val = patches.FancyBboxPatch((6.5, 1.8), 1.7, 1.5, boxstyle="round,pad=0.1",
                                      ec="#DD6B20", fc="#FEEBC8", lw=1.8)
    ax.add_patch(rect_val)
    ax.text(7.35, 2.7, "XÁC THỰC (VAL)\n(Tháng 03-04/2018)",
            ha="center", va="center", fontsize=9, fontweight="bold", color="#7B341E")
    ax.text(7.35, 2.1, "Chọn mô hình tối ưu\nvà cố định ngưỡng",
            ha="center", va="center", fontsize=7.5, color="#7B341E")

    # Buffer Gap
    rect_gap2 = patches.FancyBboxPatch((8.2, 1.8), 1.6, 1.5, boxstyle="round,pad=0.1",
                                       ec="#718096", fc="#EDF2F7", lw=1.5, ls="--")
    ax.add_patch(rect_gap2)
    ax.text(9.0, 2.6, "BUFFER 60 NGÀY\n(Tháng 05-06/2018)",
            ha="center", va="center", fontsize=8.5, fontweight="bold", color="#4A5568")
    ax.text(9.0, 2.05, "Chờ nhãn Val thành thục\ntrước ngày ra quyết định",
            ha="center", va="center", fontsize=7.2, color="#4A5568")

    # Sealed Test block
    rect_test = patches.FancyBboxPatch((9.8, 1.8), 1.7, 1.5, boxstyle="round,pad=0.1",
                                       ec="#2F855A", fc="#C6F6D5", lw=1.8)
    ax.add_patch(rect_test)
    ax.text(10.65, 2.7, "KIỂM TRA (SEALED TEST)\n(Tháng 07-08/2018)",
            ha="center", va="center", fontsize=9, fontweight="bold", color="#22543D")
    ax.text(10.65, 2.1, "Đánh giá 1 lần duy nhất\nKhông chỉnh sửa mô hình",
            ha="center", va="center", fontsize=7.5, color="#22543D")

    # Bottom notes
    ax.text(6.0, 0.7, "NGUYÊN TẮC NGĂN NGỪA RÒ RỈ DỮ LIỆU (DATA LEAKAGE PREVENTION):\n"
                      "• Mọi đặc trưng (Features) chỉ được tính toán tại thời điểm đặt hàng (prediction_cutoff_ts).\n"
                      "• Tuyệt đối không dùng các mốc thời gian sau đặt hàng (ngày duyệt, ngày giao cho vận chuyển, ngày giao khách).\n"
                      "• Tập Test được niêm phong hoàn toàn và chỉ mở ra đánh giá sau khi mô hình đã được cố định trước ngày 01/07/2018.",
            ha="center", va="center", fontsize=9, color="#2D3748",
            bbox=dict(boxstyle="square,pad=0.6", fc="#F7FAFC", ec="#CBD5E0", lw=1.2))

    plt.tight_layout()
    p1 = out_dir / "hinh_3_5_phan_chia_cohort_thoi_gian.png"
    plt.savefig(p1, bbox_inches="tight")
    plt.close()

    # -------------------------------------------------------------
    # 2. HÌNH 3.7: SƠ ĐỒ KIẾN TRÚC CLIENT - SERVER - DUCKDB
    # -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(14, 8), dpi=300)
    ax.set_xlim(-0.5, 14.5)
    ax.set_ylim(-0.5, 9.5)
    ax.axis("off")

    ax.text(7.0, 9.0, "KIẾN TRÚC PHÂN PHỐI DỮ LIỆU 3 LỚP (CLIENT - SERVER - DUCKDB) & CẤU TRÚC 5 TAB DASHBOARD",
            fontsize=13, fontweight="bold", ha="center", color="#1A365D")

    # Layer 1
    rect_t1 = patches.FancyBboxPatch((0.5, 5.8), 3.8, 2.7, boxstyle="round,pad=0.15",
                                     ec="#3182CE", fc="#EBF8FF", lw=1.8)
    ax.add_patch(rect_t1)
    ax.text(2.4, 8.1, "LỚP 1: TRÌNH DUYỆT (CLIENT)", fontsize=10.5, fontweight="bold", ha="center", color="#2B6CB0")
    ax.text(2.4, 6.9, "• Vanilla HTML5 / CSS3 / JavaScript\n"
                      "• Vẽ biểu đồ trực tiếp bằng Pure SVG\n"
                      "• Bộ lọc 3 chiều: Tháng / Bang / Trạng thái\n"
                      "• Active Filter Chips (bỏ chọn linh hoạt)\n"
                      "• Bảo vệ mẫu nhỏ (n < 20 cảnh báo mờ)\n"
                      "• Gán textContent ngăn ngừa mã độc XSS",
            fontsize=8.5, va="center", ha="center", color="#2D3748")

    # Layer 2
    rect_t2 = patches.FancyBboxPatch((5.3, 5.8), 4.0, 2.7, boxstyle="round,pad=0.15",
                                     ec="#DD6B20", fc="#FFFAF0", lw=1.8)
    ax.add_patch(rect_t2)
    ax.text(7.3, 8.1, "LỚP 2: DỊCH VỤ API (PYTHON HTTP)", fontsize=10.5, fontweight="bold", ha="center", color="#C05621")
    ax.text(7.3, 6.9, "• Python ThreadingHTTPServer (Zero-dependency)\n"
                      "• 3 Tuyến API RESTful chuẩn hóa:\n"
                      "   + /api/options (Danh mục bộ lọc)\n"
                      "   + /api/dashboard (Số liệu 4 Tab vận hành)\n"
                      "   + /api/predictions (Số liệu Tab Dự đoán ML)\n"
                      "• Parameterized Queries (?) chống SQL Injection\n"
                      "• Kiểm tra định dạng Order ID (32 ký tự hex)",
            fontsize=8.5, va="center", ha="center", color="#2D3748")

    # Layer 3
    rect_t3 = patches.FancyBboxPatch((10.3, 5.8), 3.8, 2.7, boxstyle="round,pad=0.15",
                                     ec="#38A169", fc="#F0FFF4", lw=1.8)
    ax.add_patch(rect_t3)
    ax.text(12.2, 8.1, "LỚP 3: DUCKDB LAKEHOUSE", fontsize=10.5, fontweight="bold", ha="center", color="#276749")
    ax.text(12.2, 6.9, "• Kết nối đọc an toàn: read_only=True\n"
                      "• Chống Lock DB khi nhiều user truy cập\n"
                      "• 4 Data Marts báo cáo tầng Gold:\n"
                      "   + dashboard_order_daily\n"
                      "   + dashboard_category_daily\n"
                      "   + dashboard_seller_daily\n"
                      "   + dashboard_customer_order_base\n"
                      "• Bảng Fact: gold.fact_delivery_predictions",
            fontsize=8.5, va="center", ha="center", color="#2D3748")

    # Connectors
    ax.annotate("", xy=(5.2, 7.15), xytext=(4.4, 7.15),
                arrowprops=dict(arrowstyle="<->", color="#4A5568", lw=2.0))
    ax.text(4.8, 7.4, "HTTP / JSON\nRequest/Response", fontsize=7.5, ha="center", color="#4A5568", fontweight="semibold")

    ax.annotate("", xy=(10.2, 7.15), xytext=(9.4, 7.15),
                arrowprops=dict(arrowstyle="<->", color="#4A5568", lw=2.0))
    ax.text(9.8, 7.4, "DuckDB SQL\nread_only=True", fontsize=7.5, ha="center", color="#4A5568", fontweight="semibold")

    # Tabs
    rect_tabs = patches.FancyBboxPatch((0.5, 0.5), 13.6, 4.6, boxstyle="round,pad=0.15",
                                       ec="#805AD5", fc="#FAF5FF", lw=1.8)
    ax.add_patch(rect_tabs)
    ax.text(7.3, 4.7, "CẤU TRÚC PHÂN BỔ 5 TAB CHỨC NĂNG CỦA HỆ THỐNG ĐIỀU HÀNH WEB DASHBOARD",
            fontsize=11, fontweight="bold", ha="center", color="#553C9A")

    tabs = [
        ("Tab 1: Tổng quan vận hành",
         "• 6 Thẻ KPI tổng hợp MoM\n• Biểu đồ đường xu hướng 12 tháng\n• Phân bố trễ 5 bang cao nhất\n• Tỷ trọng doanh số theo ngành hàng",
         "#3182CE", "#EBF8FF", 0.8),
        ("Tab 2: Chẩn đoán giao trễ",
         "• Phân rã thời gian 3 chặng logistics\n• Ma trận rủi ro trễ theo hẹn giao\n• Điểm nghẽn giao hàng từng bang\n• Bảng phân tích chi tiết đa chiều",
         "#DD6B20", "#FFFAF0", 3.4),
        ("Tab 3: Sản phẩm & Người bán",
         "• Cơ cấu 8 nhóm hàng chủ lực (Pareto)\n• Xu hướng tăng trưởng từng ngành\n• Top 10 người bán lớn nhất\n• Phân tích khoảng cách người bán",
         "#D69E2E", "#FFFFF0", 6.0),
        ("Tab 4: Khách hàng & Đánh giá",
         "• Tỷ trọng khách mua mới vs quay lại\n• Điểm review trung bình theo tháng\n• Tỷ lệ đánh giá tiêu cực (1-2 sao)\n• Đối chiếu đơn trễ vs điểm số",
         "#805AD5", "#F3E8FF", 8.6),
        ("Tab 5: Dự đoán giao hàng & XAI",
         "• Đọc trực tiếp gold.fact_delivery_predictions\n• Phân bổ 3 vùng rủi ro (Đỏ/Vàng/Xanh)\n• Bảng 30 đơn hàng nguy cơ cao nhất\n• Giải thích Top 3 nguyên nhân trễ",
         "#E53E3E", "#FFF5F5", 11.2)
    ]

    for title, desc, ec, fc, x in tabs:
        box = patches.FancyBboxPatch((x, 1.0), 2.4, 3.3, boxstyle="round,pad=0.1", ec=ec, fc=fc, lw=1.5)
        ax.add_patch(box)
        ax.text(x + 1.2, 3.9, title, fontsize=9, fontweight="bold", ha="center", color=ec)
        ax.text(x + 1.2, 2.4, desc, fontsize=7.6, ha="center", va="center", color="#2D3748")

    plt.tight_layout()
    p2 = out_dir / "hinh_3_7_kien_truc_dashboard_api.png"
    plt.savefig(p2, bbox_inches="tight")
    plt.close()

    print("Generated Chapter 3 diagrams successfully:")
    print(f"  - {p1}")
    print(f"  - {p2}")


if __name__ == "__main__":
    generate_diagrams()

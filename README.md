# Olist Project — hướng dẫn chạy nhanh

Chạy các lệnh dưới đây bằng PowerShell **tại thư mục gốc dự án**. Dự án dùng Python 3.11 và DuckDB cục bộ; không cần token MotherDuck.

## Cấu trúc chính

```text
data/raw/             9 tệp CSV Olist gốc
data/warehouse/       Cơ sở dữ liệu DuckDB (Bronze → Silver → Gold)
data/ml/              Tập dữ liệu và kết quả mô hình
pipeline/             Nạp Bronze, chuẩn bị dữ liệu, huấn luyện và xuất dự báo
warehouse/            Mô hình dbt, cấu hình và kiểm định kho dữ liệu
dashboard/            Dashboard web 5 tab
tests/                Kiểm tra bằng Python
```

## Mở dashboard từ bản đã đóng gói dữ liệu

Cần có `data/warehouse/olist.duckdb` chứa bảng `gold.fact_delivery_predictions` và tệp `data/ml/models/dashboard_joint_predictions_metadata.json` để xem đủ cả 5 tab.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m dashboard.server
```

Mở <http://127.0.0.1:8501/>. Dừng máy chủ bằng `Ctrl+C`. Sau khi sửa `dashboard/server.py`, khởi động lại máy chủ; sau khi sửa giao diện, tải lại trình duyệt bằng `Ctrl+F5`.

## Dựng lại dữ liệu và mô hình từ CSV gốc

Chỉ dùng chuỗi lệnh này trong bản dựng mới có đủ 9 CSV ở `data/raw/`. Chạy lần lượt sau khi đã cài môi trường ở trên:

```powershell
.venv\Scripts\python.exe -m pipeline.bronze
.venv\Scripts\dbt.exe run --project-dir warehouse --profiles-dir warehouse
.venv\Scripts\dbt.exe test --project-dir warehouse --profiles-dir warehouse
.venv\Scripts\python.exe -m pipeline.ml_dataset
.venv\Scripts\python.exe -m pipeline.label_availability
.venv\Scripts\python.exe -m pipeline.regression_baseline
.venv\Scripts\python.exe -m pipeline.classification_baseline
.venv\Scripts\python.exe -m pipeline.classification_compare
.venv\Scripts\python.exe -m pipeline.historical_selection
.venv\Scripts\python.exe -m pipeline.historical_test
.venv\Scripts\python.exe -m pipeline.hybrid_alert_policy
.venv\Scripts\python.exe -m pipeline.dashboard_prediction_export
.venv\Scripts\python.exe -m pipeline.explainability
.venv\Scripts\python.exe -m pipeline.save_predictions_to_gold
```

`historical_test` cố ý không ghi đè kết quả test đã có. Các thí nghiệm bổ sung và điều kiện chạy chi tiết nằm trong [pipeline/README.md](pipeline/README.md); mô hình và kiểm định kho dữ liệu nằm trong [warehouse/README.md](warehouse/README.md); định nghĩa dashboard nằm trong [dashboard/README.md](dashboard/README.md).

## Đóng gói

- **Để xem ngay:** giữ `dashboard/`, `pipeline/`, `warehouse/`, `requirements.txt`, `data/warehouse/olist.duckdb` đã đồng bộ dự báo và tệp metadata dự báo nêu trên.
- **Để tái lập toàn bộ:** giữ thêm `data/raw/`, `tests/` và các kết quả trong `data/ml/` nếu muốn lưu dấu quá trình ML.
- Không cần đóng gói `.venv/`, `.uv-cache/`, `__pycache__/`, `warehouse/target/` và `warehouse/logs/`.

`.gitignore` đang bỏ qua `data/warehouse/` và `data/ml/`; nếu giao dự án qua Git, hãy gửi hai thư mục dữ liệu cần thiết bằng tệp nén riêng.

Tab Dự đoán là mô phỏng hồi cứu trên đơn tháng 07–08/2018, không phải dự báo trực tiếp cho đơn mới.

# -*- coding: utf-8 -*-
# ==============================================================================
# CHƯƠNG 2: MÔ TẢ, PHÂN TÍCH TỔNG QUAN VỀ DỮ LIỆU  (PHIÊN BẢN HOÀN CHỈNH V2)
# ------------------------------------------------------------------------------
# Cách chạy:   python chapter2_eda_v2.py      (đặt cạnh thư mục data/raw)
# Đầu ra:      outputs/tables/chapter2/*.csv
#              outputs/figures/chapter2/hinh_2_*.png
#              outputs/tables/chapter2/tong_hop_so_lieu_chuong2.json
#
# BẢN ĐỒ MỤC BÁO CÁO  <->  BẢNG / HÌNH
#   2.1      bang_quy_mo_cac_bang.csv, thong_tin_bo_sung_bang_du_lieu.csv
#   2.2.1    hinh_2_1 (cơ cấu trạng thái)  hinh_2_2 (đơn theo tháng)
#            hinh_2_3 (tỷ lệ trễ theo tháng)  + so_sanh_dinh_nghia_giao_tre.csv
#   2.2.2    hinh_2_4 (thời gian các chặng + theo phương thức thanh toán)
#            hinh_2_5 (thời gian giao thực tế so với dự kiến)
#   2.2.3    hinh_2_6 (khoảng cách - cước phí - khối lượng)
#            hinh_2_7 (khoảng cách - độ trễ - thời gian giao)
#            hinh_2_8 (tỷ lệ trễ theo bang)
#   2.2.4    hinh_2_9 (điểm đánh giá theo tình trạng và mức độ trễ)
#   2.3.1    hinh_2_10 (tỷ lệ thiếu theo cột)  hinh_2_11 (thiếu x trạng thái)
#   2.3.2    tien_trinh_xu_ly_..., thieu_moc_theo_trang_thai.csv
#   2.3.3    hinh_2_12 (outlier)
#   2.3.4    hinh_2_13 (xung đột mã bưu chính)  xung_dot_ma_buu_chinh.csv
#   2.3.5    bang_kiem_tra_toan_ven_tham_chieu.csv, canh_bao_thoi_gian_am_...
# ==============================================================================

import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.patches import Patch, Rectangle
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ==============================================================================
# CẤU HÌNH CHUNG
# ==============================================================================
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data" / "raw"
TABLE_DIR = PROJECT_DIR / "outputs" / "tables" / "chapter2"
FIGURE_DIR = PROJECT_DIR / "outputs" / "figures" / "chapter2"
TABLE_DIR.mkdir(parents=True, exist_ok=True)
FIGURE_DIR.mkdir(parents=True, exist_ok=True)

# Định nghĩa nhãn "giao trễ".
#   False: so sánh theo timestamp (giao sau 00:00 của ngày dự kiến là trễ)  -> mặc định, 8,11%
#   True : so sánh theo ngày lịch (giao trong ngày dự kiến vẫn là đúng hạn) -> 6,77%
# Cả hai cách luôn được tính và so sánh trong so_sanh_dinh_nghia_giao_tre.csv
LATE_BY_CALENDAR_DAY = False

NGUONG_CO_MAU = 30            # tháng/nhóm có ít hơn 30 quan sát thì không vẽ tỷ lệ
NGUONG_BANG_NHO = 100         # bang có ít hơn 100 đơn được đánh dấu "cỡ mẫu nhỏ"
SEC_PER_DAY = 24 * 60 * 60
# Hộp bao lãnh thổ Brazil (xấp xỉ) dùng để phát hiện tọa độ ngoài lãnh thổ
LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX = -33.8, 5.3, -73.99, -34.7

C_MAIN, C_WARN, C_OK, C_GREY, C_ORANGE = "#2B6CB0", "#E53E3E", "#38A169", "#A0AEC0", "#DD6B20"

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["axes.titleweight"] = "bold"
sns.set_style("whitegrid")

COT_THOI_GIAN = [
    "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
    "order_delivered_customer_date", "order_estimated_delivery_date",
]
SUMMARY = {}   # gom các số liệu chính để viết báo cáo


def luu_bang(df, ten_file):
    df.to_csv(TABLE_DIR / ten_file, index=False, encoding="utf-8-sig")


def luu_hinh(ten_file, can_le=True):
    if can_le:
        plt.tight_layout()
    plt.savefig(FIGURE_DIR / ten_file, dpi=250, bbox_inches="tight")
    plt.close()


def tieu_de(txt):
    print("\n" + "=" * 8 + f" {txt} " + "=" * 8)


def nghin(x, _=None):
    return f"{int(x):,}"


def pct(a, b, nd=2):
    return round(a / b * 100, nd) if b else np.nan


def chuyen_cot_thoi_gian(df):
    df = df.copy()
    for cot in COT_THOI_GIAN:
        df[cot] = pd.to_datetime(df[cot], errors="coerce")
    return df


# ==============================================================================
# BƯỚC 1. ĐỌC DỮ LIỆU VÀ MÔ TẢ QUY MÔ (2.1)
# ==============================================================================
tieu_de("BƯỚC 1: ĐỌC 9 FILE CSV")
file_paths = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}
tables = {k: pd.read_csv(DATA_DIR / v) for k, v in file_paths.items()}
orders_dt = chuyen_cot_thoi_gian(tables["orders"])
TONG_DON = len(orders_dt)

quy_mo = pd.DataFrame([
    {"Tên bảng": k, "Tên file": file_paths[k], "Số dòng": len(d), "Số cột": d.shape[1]}
    for k, d in tables.items()
])
luu_bang(quy_mo, "bang_quy_mo_cac_bang.csv")
print(quy_mo.to_string(index=False))

# Số lượng thực thể duy nhất: lưu ý customer_id (theo đơn) khác customer_unique_id (theo người)
rv = tables["order_reviews"]
thong_tin_bo_sung = pd.DataFrame([
    ("Số customer_id (mỗi đơn một mã)", tables["customers"]["customer_id"].nunique()),
    ("Số customer_unique_id (khách hàng thực)", tables["customers"]["customer_unique_id"].nunique()),
    ("Số review_id duy nhất", rv["review_id"].nunique()),
    ("Số đơn hàng có review", rv["order_id"].nunique()),
    ("Số đơn có từ 2 review trở lên", int((rv.groupby("order_id").size() > 1).sum())),
    ("Số người bán", tables["sellers"]["seller_id"].nunique()),
    ("Số sản phẩm", tables["products"]["product_id"].nunique()),
    ("Số danh mục sản phẩm (có tên)", tables["products"]["product_category_name"].nunique()),
    ("Ngày đặt hàng sớm nhất", str(orders_dt["order_purchase_timestamp"].min())),
    ("Ngày đặt hàng muộn nhất", str(orders_dt["order_purchase_timestamp"].max())),
], columns=["Chỉ tiêu", "Giá trị"])
luu_bang(thong_tin_bo_sung, "thong_tin_bo_sung_bang_du_lieu.csv")
print(thong_tin_bo_sung.to_string(index=False))
SUMMARY["khoang_thoi_gian"] = [str(orders_dt["order_purchase_timestamp"].min()),
                               str(orders_dt["order_purchase_timestamp"].max())]
SUMMARY["khach_hang_duy_nhat"] = int(tables["customers"]["customer_unique_id"].nunique())

# Cấu trúc, thiếu, trùng, trùng khóa, hợp lệ
structure_df = pd.DataFrame([
    {"Tên bảng": k, "Tên cột": c, "Kiểu dữ liệu": str(d[c].dtype),
     "Số giá trị không thiếu": int(d[c].count()), "Tổng số dòng": len(d)}
    for k, d in tables.items() for c in d.columns
])
luu_bang(structure_df, "bang_cau_truc_va_kieu_du_lieu.csv")

missing_df = pd.DataFrame([
    {"Tên bảng": k, "Tên cột": c, "Tổng số dòng": len(d),
     "Số giá trị thiếu": int(d[c].isna().sum()),
     "Tỷ lệ thiếu (%)": pct(int(d[c].isna().sum()), len(d))}
    for k, d in tables.items() for c in d.columns
])
missing_only_df = missing_df[missing_df["Số giá trị thiếu"] > 0].sort_values(
    ["Tên bảng", "Số giá trị thiếu"], ascending=[True, False])
luu_bang(missing_df, "bang_kiem_tra_du_lieu_thieu.csv")
luu_bang(missing_only_df, "bang_cac_cot_co_du_lieu_thieu.csv")

duplicate_df = pd.DataFrame([
    {"Tên bảng": k, "Tổng số dòng": len(d), "Số dòng trùng lặp": int(d.duplicated().sum()),
     "Tỷ lệ trùng lặp (%)": pct(int(d.duplicated().sum()), len(d))}
    for k, d in tables.items()
])
luu_bang(duplicate_df, "bang_kiem_tra_du_lieu_trung_lap.csv")

key_columns = {
    "customers": ["customer_id"], "orders": ["order_id"],
    "order_items": ["order_id", "order_item_id"],
    "order_payments": ["order_id", "payment_sequential"],
    "order_reviews": ["review_id"], "products": ["product_id"],
    "sellers": ["seller_id"], "category_translation": ["product_category_name"],
}
key_df = pd.DataFrame([
    {"Tên bảng": k, "Cột khóa kiểm tra": ", ".join(c),
     "Số dòng trùng khóa": int(tables[k].duplicated(subset=c).sum()),
     "Số dòng thiếu khóa": int(tables[k][c].isna().any(axis=1).sum())}
    for k, c in key_columns.items()
])
luu_bang(key_df, "bang_kiem_tra_trung_khoa.csv")
print(key_df.to_string(index=False))

dup_reviews = rv[rv.duplicated(subset=["review_id"], keep=False)].sort_values("review_id")
luu_bang(dup_reviews, "chi_tiet_cac_dong_review_id_trung.csv")
luu_bang(
    dup_reviews.groupby("review_id").agg(
        So_dong=("review_id", "size"), So_don_hang=("order_id", "nunique"),
        So_muc_danh_gia=("review_score", "nunique")).reset_index(),
    "thong_ke_review_id_trung.csv")
SUMMARY["review_id_trung_khoa"] = int(rv.duplicated(subset=["review_id"]).sum())
SUMMARY["review_id_trung_so_dong"] = int(len(dup_reviews))

# Tính hợp lệ giá trị
validity = []


def them_kiem_tra(bang, noi_dung, tong, so_sai, ghi_chu):
    validity.append({"Tên bảng": bang, "Nội dung kiểm tra": noi_dung, "Tổng số dòng": tong,
                     "Số dòng không hợp lệ": int(so_sai),
                     "Tỷ lệ không hợp lệ (%)": pct(int(so_sai), tong), "Ghi chú": ghi_chu})


d = tables["order_reviews"]
them_kiem_tra("order_reviews", "Điểm đánh giá trong khoảng 1-5", len(d),
              (d["review_score"].notna() & ~d["review_score"].between(1, 5)).sum(), "")
d = tables["order_items"]
them_kiem_tra("order_items", "Giá sản phẩm > 0", len(d), (d["price"] <= 0).sum(), "")
them_kiem_tra("order_items", "Phí vận chuyển >= 0", len(d), (d["freight_value"] < 0).sum(), "")
d = tables["order_payments"]
them_kiem_tra("order_payments", "Giá trị thanh toán > 0", len(d), (d["payment_value"] <= 0).sum(),
              "Gồm voucher và not_defined")
d = tables["products"]
for c in ["product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]:
    them_kiem_tra("products", f"{c} >= 0", len(d), (d[c] < 0).sum(), "Giá trị thiếu chưa tính")
for sớm, muộn in [("order_purchase_timestamp", "order_approved_at"),
                  ("order_approved_at", "order_delivered_carrier_date"),
                  ("order_delivered_carrier_date", "order_delivered_customer_date")]:
    ok = orders_dt[sớm].notna() & orders_dt[muộn].notna()
    them_kiem_tra("orders", f"{sớm} <= {muộn}", len(orders_dt),
                  (ok & (orders_dt[sớm] > orders_dt[muộn])).sum(), "Chỉ so sánh khi đủ hai mốc")
validity_df = pd.DataFrame(validity)
luu_bang(validity_df, "bang_kiem_tra_tinh_hop_le.csv")

pay = tables["order_payments"]
pay_bt = pay[pay["payment_value"] <= 0]
luu_bang(pay_bt, "cac_dong_thanh_toan_bat_thuong.csv")
SUMMARY["thanh_toan_bang_0"] = {"so_dong": int(len(pay_bt)),
                                "theo_loai": pay_bt["payment_type"].value_counts().to_dict()}

# ==============================================================================
# BƯỚC 2. TẠO NHÃN ĐỘ TRỄ + SO SÁNH HAI ĐỊNH NGHĨA (2.2.1)
# ==============================================================================
tieu_de("BƯỚC 2: NHÃN ĐỘ TRỄ GIAO HÀNG")


def tinh_nhan_tre(df, theo_ngay):
    du_dk = ((df["order_status"] == "delivered")
             & df["order_delivered_customer_date"].notna()
             & df["order_estimated_delivery_date"].notna())
    if theo_ngay:
        delay = (df["order_delivered_customer_date"].dt.normalize()
                 - df["order_estimated_delivery_date"].dt.normalize()).dt.days.astype(float)
    else:
        delay = ((df["order_delivered_customer_date"] - df["order_estimated_delivery_date"])
                 .dt.total_seconds() / SEC_PER_DAY)
    delay = delay.where(du_dk)
    tre = (delay > 0).astype("Int64").where(du_dk, pd.NA)
    return du_dk, delay, tre


du_dk, delay_chinh, tre_chinh = tinh_nhan_tre(orders_dt, LATE_BY_CALENDAR_DAY)
_, delay_ts, tre_ts = tinh_nhan_tre(orders_dt, False)
_, delay_ngay, tre_ngay = tinh_nhan_tre(orders_dt, True)

orders_analysis = orders_dt.copy()
orders_analysis["delivery_delay_days"] = delay_chinh
orders_analysis["is_delayed"] = tre_chinh
orders_analysis["tong_thoi_gian_giao_ngay"] = (
    (orders_analysis["order_delivered_customer_date"] - orders_analysis["order_purchase_timestamp"])
    .dt.total_seconds() / SEC_PER_DAY).where(du_dk)
orders_analysis["thoi_gian_du_kien_ngay"] = (
    (orders_analysis["order_estimated_delivery_date"] - orders_analysis["order_purchase_timestamp"])
    .dt.total_seconds() / SEC_PER_DAY).where(du_dk)
luu_bang(orders_analysis, "du_lieu_don_hang_co_bien_do_tre.csv")

orders_delivered = orders_analysis[orders_analysis["is_delayed"].notna()].copy()
orders_delivered["is_delayed"] = orders_delivered["is_delayed"].astype(int)
SO_DU_DK = int(du_dk.sum())
SO_TRE = int(orders_delivered["is_delayed"].sum())
SO_DUNG_HAN = SO_DU_DK - SO_TRE
print(f"Tổng đơn {TONG_DON:,} | đủ điều kiện {SO_DU_DK:,} | trễ {SO_TRE:,} ({pct(SO_TRE, SO_DU_DK)}%)")

bang_nhan = (orders_analysis["is_delayed"].map({0: "Đúng hạn hoặc giao sớm", 1: "Giao trễ"})
             .fillna("Chưa xác định").value_counts().rename_axis("Nhãn giao hàng")
             .reset_index(name="Số lượng"))
luu_bang(bang_nhan, "thong_ke_nhan_tinh_trang_giao_hang.csv")

# Phân rã 2.971 đơn "chưa xác định"
khong_xd = orders_analysis[orders_analysis["is_delayed"].isna()]
phan_ra_khong_xd = khong_xd["order_status"].value_counts().rename_axis("Trạng thái").reset_index(name="Số đơn")
phan_ra_khong_xd["Ghi chú"] = np.where(
    phan_ra_khong_xd["Trạng thái"] == "delivered", "Đã giao nhưng thiếu ngày giao thực tế",
    np.where(phan_ra_khong_xd["Trạng thái"] == "canceled",
             "Gồm 6 đơn có ngày giao nhưng trạng thái canceled (bị loại khỏi nhãn)",
             "Chưa hoàn tất giao hàng"))
luu_bang(phan_ra_khong_xd, "phan_ra_don_chua_xac_dinh_nhan.csv")
print(phan_ra_khong_xd.to_string(index=False))

# So sánh hai định nghĩa
tre_ts_n = int((tre_ts == 1).sum())
tre_ngay_n = int((tre_ngay == 1).sum())
so_sanh_dn = pd.DataFrame([
    {"Định nghĩa": "Theo timestamp (giao sau 00:00 ngày dự kiến là trễ)", "Số đơn trễ": tre_ts_n,
     "Số đơn đủ điều kiện": SO_DU_DK, "Tỷ lệ trễ (%)": pct(tre_ts_n, SO_DU_DK)},
    {"Định nghĩa": "Theo ngày lịch (giao trong ngày dự kiến là đúng hạn)", "Số đơn trễ": tre_ngay_n,
     "Số đơn đủ điều kiện": SO_DU_DK, "Tỷ lệ trễ (%)": pct(tre_ngay_n, SO_DU_DK)},
    {"Định nghĩa": "Chênh lệch: giao đúng ngày dự kiến nhưng bị gắn nhãn trễ theo timestamp",
     "Số đơn trễ": tre_ts_n - tre_ngay_n, "Số đơn đủ điều kiện": SO_DU_DK,
     "Tỷ lệ trễ (%)": pct(tre_ts_n - tre_ngay_n, SO_DU_DK)},
])
luu_bang(so_sanh_dn, "so_sanh_dinh_nghia_giao_tre.csv")
print(so_sanh_dn.to_string(index=False))
SUMMARY["nhan_tre"] = {"tong_don": TONG_DON, "du_dieu_kien": SO_DU_DK, "tre": SO_TRE,
                       "ty_le_tre_pct": pct(SO_TRE, SO_DU_DK),
                       "tre_theo_timestamp": tre_ts_n, "tre_theo_ngay": tre_ngay_n,
                       "ty_le_theo_ngay_pct": pct(tre_ngay_n, SO_DU_DK),
                       "do_tre_trung_binh_trong_nhom_tre": float(delay_ts[delay_ts > 0].mean()),
                       "do_tre_trung_vi_trong_nhom_tre": float(delay_ts[delay_ts > 0].median())}

# ==============================================================================
# BƯỚC 3. 2.2.1 – CƠ CẤU VÀ XU HƯỚNG ĐƠN HÀNG
# ==============================================================================
tieu_de("BƯỚC 3: CƠ CẤU VÀ XU HƯỚNG ĐƠN HÀNG")

# --- Hình 2.1: cơ cấu trạng thái ---
tt = orders_dt["order_status"].value_counts().rename_axis("order_status").reset_index(name="so_don")
tt["ty_le_pct"] = tt["so_don"] / TONG_DON * 100
luu_bang(tt, "thong_ke_trang_thai_don_hang.csv")
fig, ax = plt.subplots(figsize=(10, 5.5))
tt_ve = tt.sort_values("so_don")
bars = ax.barh(tt_ve["order_status"], tt_ve["so_don"],
               color=[C_MAIN if s == "delivered" else C_GREY for s in tt_ve["order_status"]])
for b, r in zip(bars, tt_ve.itertuples()):
    ax.text(b.get_width() * 1.15, b.get_y() + b.get_height() / 2,
            f"{r.so_don:,} ({r.ty_le_pct:.2f}%)", va="center", fontsize=10)
ax.set_xscale("log")
ax.set_xlim(1, tt["so_don"].max() * 12)
ax.set_title("Cơ cấu đơn hàng theo trạng thái (thang logarit)")
ax.set_xlabel("Số đơn hàng (thang logarit)")
ax.set_ylabel("Trạng thái đơn hàng")
luu_hinh("hinh_2_1_co_cau_trang_thai_don_hang.png")

# --- Bảng theo tháng (đủ mọi tháng, kể cả tháng không có đơn) ---
thang_all = orders_analysis["order_purchase_timestamp"].dt.to_period("M")
chi_so_thang = pd.period_range(thang_all.min(), thang_all.max(), freq="M")
bang_thang = pd.DataFrame(index=chi_so_thang)
bang_thang["tong_so_don"] = thang_all.value_counts().reindex(chi_so_thang, fill_value=0)
od = orders_delivered.assign(m=orders_delivered["order_purchase_timestamp"].dt.to_period("M"))
g = od.groupby("m").agg(so_don_du_dieu_kien=("order_id", "nunique"), so_don_giao_tre=("is_delayed", "sum"))
bang_thang = bang_thang.join(g).fillna({"so_don_du_dieu_kien": 0, "so_don_giao_tre": 0})
bang_thang[["so_don_du_dieu_kien", "so_don_giao_tre"]] = bang_thang[["so_don_du_dieu_kien", "so_don_giao_tre"]].astype(int)
bang_thang["ty_le_giao_tre_pct"] = (bang_thang["so_don_giao_tre"]
                                    / bang_thang["so_don_du_dieu_kien"].where(bang_thang["so_don_du_dieu_kien"] > 0) * 100)
bang_thang = bang_thang.reset_index().rename(columns={"index": "thang"})
bang_thang["thang"] = bang_thang["thang"].astype(str)
luu_bang(bang_thang, "thong_ke_don_hang_va_do_tre_theo_thang.csv")
print(bang_thang.to_string(index=False))

# --- Hình 2.2: số đơn theo tháng (đủ tháng, tháng thiếu dữ liệu tô xám) ---
fig, ax = plt.subplots(figsize=(12, 5.5))
mau = [C_GREY if (s.startswith("2016") or s >= "2018-09") else C_MAIN for s in bang_thang["thang"]]
ax.bar(bang_thang["thang"], bang_thang["tong_so_don"], color=mau)
i_max = bang_thang["tong_so_don"].idxmax()
ax.annotate(f"Đỉnh: {bang_thang.loc[i_max, 'tong_so_don']:,} đơn\n({bang_thang.loc[i_max, 'thang']})",
            xy=(i_max, bang_thang.loc[i_max, "tong_so_don"]), xytext=(-70, -5),
            textcoords="offset points", fontsize=10, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="gray"))
ax.set_title("Số lượng đơn hàng theo tháng đặt hàng")
ax.set_xlabel("Tháng đặt hàng")
ax.set_ylabel("Số đơn hàng")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(nghin))
ax.tick_params(axis="x", rotation=60)
ax.legend(handles=[Patch(color=C_MAIN, label="Giai đoạn dữ liệu đầy đủ"),
                   Patch(color=C_GREY, label="Giai đoạn khởi đầu (2016) / dữ liệu bị cắt (từ 09/2018)")],
          loc="upper center", bbox_to_anchor=(.5, -.28), ncol=2, fontsize=9)
luu_hinh("hinh_2_2_so_don_theo_thang.png")

# --- Hình 2.3: tỷ lệ trễ theo tháng ---
bt = bang_thang.copy()
bt["ty_le_ve"] = bt["ty_le_giao_tre_pct"].where(bt["so_don_du_dieu_kien"] >= NGUONG_CO_MAU)
ty_le_tb = SO_TRE / SO_DU_DK * 100
fig, ax = plt.subplots(figsize=(13, 5.8))
ax2 = ax.twinx()
ax2.bar(bt["thang"], bt["so_don_du_dieu_kien"], color=C_GREY, alpha=0.25)
ax2.set_ylabel("Số đơn đủ điều kiện (cột xám)")
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(nghin))
ax2.grid(False)
ax.set_zorder(ax2.get_zorder() + 1)
ax.patch.set_visible(False)
ax.plot(bt["thang"], bt["ty_le_ve"], marker="o", linewidth=2, color=C_MAIN, label="Tỷ lệ giao trễ")
ax.axhline(ty_le_tb, color=C_WARN, linestyle="--", alpha=0.8, label=f"Trung bình toàn kỳ ({ty_le_tb:.1f}%)")
for _, r in bt.nlargest(3, "ty_le_ve").iterrows():
    ax.annotate(f"{r['ty_le_ve']:.1f}%", xy=(r["thang"], r["ty_le_ve"]), xytext=(0, 9),
                textcoords="offset points", ha="center", fontsize=9, fontweight="bold")
ax.set_ylim(0, bt["ty_le_ve"].max() * 1.2)
ax.set_title(f"Tỷ lệ giao trễ theo tháng (chỉ vẽ tháng có ≥ {NGUONG_CO_MAU} đơn đủ điều kiện)")
ax.set_xlabel("Tháng đặt hàng")
ax.set_ylabel("Tỷ lệ giao trễ (%)")
ax.tick_params(axis="x", rotation=60)
ax.legend(loc="upper left", fontsize=10)
luu_hinh("hinh_2_3_ty_le_giao_tre_theo_thang.png")

# ==============================================================================
# BƯỚC 4. 2.2.2 – THỜI GIAN LƯU CHUYỂN QUA TỪNG CHẶNG
# ==============================================================================
tieu_de("BƯỚC 4: THỜI GIAN CÁC CHẶNG LOGISTICS")
cac_chang = {
    "thoi_gian_duyet_ngay": ("order_approved_at", "order_purchase_timestamp", "Đặt hàng -> Duyệt đơn"),
    "thoi_gian_ban_giao_vc_ngay": ("order_delivered_carrier_date", "order_approved_at", "Duyệt đơn -> Bàn giao vận chuyển"),
    "thoi_gian_van_chuyen_ngay": ("order_delivered_customer_date", "order_delivered_carrier_date", "Bàn giao vận chuyển -> Giao khách"),
}
orders_stage = orders_analysis.copy()
for cot, (sau, truoc, _) in cac_chang.items():
    orders_stage[cot] = (orders_stage[sau] - orders_stage[truoc]).dt.total_seconds() / SEC_PER_DAY
cot_chang = list(cac_chang)
ten_chang = {c: v[2] for c, v in cac_chang.items()}

bao_cao = []
for cot in cot_chang:
    co = int(orders_stage[cot].notna().sum())
    am = int((orders_stage[cot] < 0).sum())
    bao_cao.append({
        "Chặng xử lý": ten_chang[cot], "Tổng số đơn": TONG_DON,
        "Số đơn thiếu dữ liệu (thiếu 1 trong 2 mốc)": TONG_DON - co,
        "Tỷ lệ thiếu dữ liệu (%)": pct(TONG_DON - co, TONG_DON),
        "Số đơn có đủ dữ liệu": co, "Số đơn thời gian âm (bất thường)": am,
        "Tỷ lệ bất thường trên số đủ dữ liệu (%)": pct(am, co),
        "Số đơn hợp lệ dùng để thống kê": int((orders_stage[cot] >= 0).sum()),
    })
bang_canh_bao = pd.DataFrame(bao_cao)
luu_bang(bang_canh_bao, "canh_bao_thoi_gian_am_cac_chang.csv")
print(bang_canh_bao.to_string(index=False))

stage_ok = orders_stage.copy()
for cot in cot_chang:
    stage_ok.loc[stage_ok[cot] < 0, cot] = np.nan
tk_chang = stage_ok[cot_chang].describe(percentiles=[.25, .5, .75, .95]).T.reset_index()
tk_chang = tk_chang.rename(columns={"index": "Chặng xử lý"})
tk_chang["Chặng xử lý"] = tk_chang["Chặng xử lý"].map(ten_chang)
luu_bang(tk_chang, "thong_ke_thoi_gian_cac_chang.csv")
print(tk_chang.to_string(index=False))

# Độ lớn của các giá trị âm (chặng duyệt -> bàn giao) và trạng thái đơn tương ứng
am2 = orders_stage.loc[orders_stage["thoi_gian_ban_giao_vc_ngay"] < 0]
am_mo_ta = am2["thoi_gian_ban_giao_vc_ngay"].describe().rename("Giá trị (ngày)").reset_index()
am_mo_ta.columns = ["Chỉ tiêu", "Giá trị (ngày)"]
luu_bang(am_mo_ta, "mo_ta_thoi_gian_am_duyet_ban_giao.csv")
luu_bang(am2["order_status"].value_counts().rename_axis("Trạng thái").reset_index(name="Số đơn"),
         "thoi_gian_am_duyet_ban_giao_theo_trang_thai.csv")
SUMMARY["thoi_gian_am_duyet_ban_giao"] = {
    "so_don": int(len(am2)), "trung_vi": float(am2["thoi_gian_ban_giao_vc_ngay"].median()),
    "nho_nhat": float(am2["thoi_gian_ban_giao_vc_ngay"].min()),
    "theo_trang_thai": am2["order_status"].value_counts().to_dict(),
    "trong_vong_1_ngay_pct": float((am2["thoi_gian_ban_giao_vc_ngay"] > -1).mean() * 100)}

# Thời gian duyệt đơn theo phương thức thanh toán (giải thích phân phối hai nhóm của chặng 1)
pay_first = (tables["order_payments"].sort_values(["order_id", "payment_sequential"])
             .groupby("order_id")["payment_type"].first())
o_pay = stage_ok[["order_id", "thoi_gian_duyet_ngay"]].join(pay_first, on="order_id")
tg_duyet_pt = (o_pay.dropna(subset=["thoi_gian_duyet_ngay", "payment_type"])
               .groupby("payment_type")["thoi_gian_duyet_ngay"]
               .agg(So_don="count", Trung_binh="mean", Trung_vi="median",
                    P75=lambda s: s.quantile(.75), P95=lambda s: s.quantile(.95)).reset_index()
               .sort_values("So_don", ascending=False))
tg_duyet_pt["Ty_le_don_pct"] = tg_duyet_pt["So_don"] / tg_duyet_pt["So_don"].sum() * 100
luu_bang(tg_duyet_pt.round(3), "thoi_gian_duyet_don_theo_phuong_thuc_thanh_toan.csv")
print(tg_duyet_pt.round(3).to_string(index=False))
SUMMARY["duyet_don_theo_thanh_toan"] = tg_duyet_pt.round(3).to_dict("records")

# --- Hình 2.4 ---
fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.5, 1]})
dv = stage_ok[cot_chang].melt(var_name="c", value_name="ngay").dropna()
nhan_ngan = {"thoi_gian_duyet_ngay": "Đặt hàng →\nDuyệt đơn",
             "thoi_gian_ban_giao_vc_ngay": "Duyệt đơn →\nBàn giao VC",
             "thoi_gian_van_chuyen_ngay": "Bàn giao VC →\nGiao khách"}
dv["Chặng"] = dv["c"].map(nhan_ngan)
dv["ngay_ve"] = dv["ngay"].clip(lower=1e-3)
sns.boxplot(data=dv, x="Chặng", y="ngay_ve", order=list(nhan_ngan.values()), showfliers=False,
            color="#90CDF4", ax=axes[0], whis=(5, 95))
axes[0].set_yscale("log")
axes[0].set_ylim(4e-3, 300)
for i, cot in enumerate(cot_chang):
    s = stage_ok[cot].dropna()
    axes[0].text(i, 90, f"Median {s.median():.2f}\nTB {s.mean():.2f}\nP95 {s.quantile(.95):.1f}",
                 ha="center", va="center", fontsize=9, bbox=dict(boxstyle="round", fc="white", alpha=.9))
axes[0].set_title("(a) Thời gian từng chặng (ngày, thang log, râu = P5–P95)")
axes[0].set_xlabel("")
axes[0].set_ylabel("Số ngày (thang logarit)")
pt = tg_duyet_pt[tg_duyet_pt["So_don"] >= NGUONG_CO_MAU]
b = axes[1].bar(pt["payment_type"], pt["Trung_vi"], color=[C_ORANGE if p == "boleto" else C_MAIN for p in pt["payment_type"]])
for bb, r in zip(b, pt.itertuples()):
    axes[1].text(bb.get_x() + bb.get_width() / 2, bb.get_height() + 0.03,
                 f"{r.Trung_vi:.2f} ngày\n(n={r.So_don:,})", ha="center", fontsize=9)
axes[1].set_title("(b) Trung vị thời gian duyệt đơn theo phương thức thanh toán")
axes[1].set_xlabel("Phương thức thanh toán (của lần thanh toán đầu tiên)")
axes[1].set_ylabel("Trung vị (ngày)")
axes[1].set_ylim(0, pt["Trung_vi"].max() * 1.3)
luu_hinh("hinh_2_4_thoi_gian_cac_chang_logistics.png")

# --- Tổng thời gian giao thực tế so với dự kiến (biến mục tiêu của Mô hình 1) ---
tong_tg = orders_delivered["tong_thoi_gian_giao_ngay"]
du_kien = orders_delivered["thoi_gian_du_kien_ngay"]
chenh = du_kien - tong_tg
tk_tong = pd.DataFrame({"Thời gian giao thực tế (ngày)": tong_tg.describe(percentiles=[.25, .5, .75, .95]),
                        "Thời gian dự kiến (ngày)": du_kien.describe(percentiles=[.25, .5, .75, .95]),
                        "Dự kiến trừ thực tế (ngày)": chenh.describe(percentiles=[.25, .5, .75, .95])})
tk_tong = tk_tong.round(2).reset_index().rename(columns={"index": "Chỉ tiêu"})
luu_bang(tk_tong, "thong_ke_tong_thoi_gian_giao.csv")
print(tk_tong.to_string(index=False))
SUMMARY["tong_thoi_gian_giao"] = {
    "thuc_te_tb": float(tong_tg.mean()), "thuc_te_trung_vi": float(tong_tg.median()),
    "thuc_te_p95": float(tong_tg.quantile(.95)), "thuc_te_max": float(tong_tg.max()),
    "du_kien_tb": float(du_kien.mean()), "du_kien_trung_vi": float(du_kien.median()),
    "chenh_tb": float(chenh.mean()), "chenh_trung_vi": float(chenh.median()),
    "ty_le_giao_som_hon_du_kien_pct": float((chenh > 0).mean() * 100)}

fig, ax = plt.subplots(figsize=(11, 5.5))
bins = np.linspace(0, 70, 71)
ax.hist(tong_tg.clip(upper=70), bins=bins, alpha=0.65, color=C_MAIN, label="Thực tế (đặt hàng → giao khách)")
ax.hist(du_kien.clip(upper=70), bins=bins, alpha=0.55, color=C_ORANGE, label="Dự kiến (đặt hàng → ngày hẹn)")
ax.axvline(tong_tg.median(), color=C_MAIN, linestyle="--")
ax.axvline(du_kien.median(), color=C_ORANGE, linestyle="--")
ax.text(tong_tg.median() + .8, ax.get_ylim()[1] * .92, f"Median thực tế = {tong_tg.median():.1f} ngày", color=C_MAIN, fontsize=10)
ax.text(du_kien.median() + .8, ax.get_ylim()[1] * .82, f"Median dự kiến = {du_kien.median():.1f} ngày", color=C_ORANGE, fontsize=10)
ax.set_title("Thời gian giao hàng thực tế so với thời gian dự kiến (đơn đã giao, gộp giá trị >70 ngày)")
ax.set_xlabel("Số ngày kể từ lúc đặt hàng")
ax.set_ylabel("Số đơn hàng")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(nghin))
ax.legend()
luu_hinh("hinh_2_5_thoi_gian_giao_thuc_te_va_du_kien.png")

# ==============================================================================
# BƯỚC 5. TỌA ĐỘ ĐẠI DIỆN THEO MÃ BƯU CHÍNH VÀ KHOẢNG CÁCH (phục vụ 2.2.3, 2.3.4)
# ==============================================================================
tieu_de("BƯỚC 5: TỌA ĐỘ MÃ BƯU CHÍNH VÀ KHOẢNG CÁCH ĐỊA LÝ")
geo_raw = tables["geolocation"]
geo = geo_raw.dropna(subset=["geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng"])
zip_stat = geo.groupby("geolocation_zip_code_prefix").agg(
    latitude=("geolocation_lat", "mean"), longitude=("geolocation_lng", "mean"),
    lat_med=("geolocation_lat", "median"), lng_med=("geolocation_lng", "median"),
    n_ban_ghi=("geolocation_lat", "size"),
    lat_std=("geolocation_lat", "std"), lng_std=("geolocation_lng", "std"),
    n_bang=("geolocation_state", "nunique"), n_ten_tp=("geolocation_city", "nunique")).reset_index()
geo_mean = zip_stat[["geolocation_zip_code_prefix", "latitude", "longitude"]]
geo_med = zip_stat[["geolocation_zip_code_prefix", "lat_med", "lng_med"]].rename(
    columns={"lat_med": "latitude", "lng_med": "longitude"})
luu_bang(geo_mean, "toa_do_dai_dien_theo_ma_buu_chinh.csv")


def tao_bang_toa_do(df, cot_id, cot_zip, tien_to, bang_geo):
    kq = df[[cot_id, cot_zip]].merge(bang_geo, left_on=cot_zip, right_on="geolocation_zip_code_prefix",
                                     how="left", validate="many_to_one")
    return kq[[cot_id, "latitude", "longitude"]].rename(
        columns={"latitude": f"{tien_to}_lat", "longitude": f"{tien_to}_lng"})


def haversine_distance(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def khoang_cach_theo_don(bang_geo):
    kh = tao_bang_toa_do(tables["customers"], "customer_id", "customer_zip_code_prefix", "customer", bang_geo)
    nb = tao_bang_toa_do(tables["sellers"], "seller_id", "seller_zip_code_prefix", "seller", bang_geo)
    don_kh = tables["orders"][["order_id", "customer_id"]].merge(kh, on="customer_id", how="left", validate="one_to_one")
    don_nb = (tables["order_items"][["order_id", "seller_id"]].drop_duplicates()
              .merge(nb, on="seller_id", how="left", validate="many_to_one")
              .merge(don_kh[["order_id", "customer_lat", "customer_lng"]], on="order_id", how="inner", validate="many_to_one"))
    hop_le = don_nb.dropna(subset=["customer_lat", "customer_lng", "seller_lat", "seller_lng"]).copy()
    hop_le["distance_km"] = haversine_distance(hop_le["customer_lat"], hop_le["customer_lng"],
                                               hop_le["seller_lat"], hop_le["seller_lng"])
    kq = hop_le.groupby("order_id").agg(average_distance_km=("distance_km", "mean"),
                                        number_of_sellers=("seller_id", "nunique")).reset_index()
    return kq, don_nb, don_kh


dist_mean, don_nb_mean, don_kh_mean = khoang_cach_theo_don(geo_mean)
dist_med, _, _ = khoang_cach_theo_don(geo_med)

delivery_distance = (
    orders_analysis[["order_id", "customer_id", "order_status", "order_purchase_timestamp", "is_delayed",
                     "delivery_delay_days", "tong_thoi_gian_giao_ngay", "thoi_gian_du_kien_ngay"]]
    .merge(tables["customers"][["customer_id", "customer_state"]], on="customer_id", how="left", validate="many_to_one")
    .merge(dist_mean, on="order_id", how="left", validate="one_to_one"))
luu_bang(delivery_distance, "du_lieu_do_tre_va_khoang_cach_dia_ly.csv")

# Phân rã 1.264 đơn không tính được khoảng cách
co_kc = delivery_distance["average_distance_km"].notna()
don_co_item = delivery_distance["order_id"].isin(tables["order_items"]["order_id"])
kh_thieu = delivery_distance["order_id"].isin(don_kh_mean.loc[don_kh_mean["customer_lat"].isna(), "order_id"])
ly_do = np.select(
    [co_kc, ~don_co_item, kh_thieu],
    ["Có khoảng cách", "Đơn không có sản phẩm (order_items)", "Thiếu tọa độ khách hàng (mã bưu chính không có trong geolocation)"],
    default="Thiếu tọa độ người bán")
phan_ra_kc = pd.Series(ly_do).value_counts().rename_axis("Lý do").reset_index(name="Số đơn")
phan_ra_kc["Tỷ lệ (%)"] = (phan_ra_kc["Số đơn"] / TONG_DON * 100).round(2)
luu_bang(phan_ra_kc, "phan_ra_don_thieu_khoang_cach.csv")
print(phan_ra_kc.to_string(index=False))
thieu_kc_theo_tt = (delivery_distance.loc[~co_kc & ~don_co_item, "order_status"]
                    .value_counts().rename_axis("Trạng thái").reset_index(name="Số đơn"))
luu_bang(thieu_kc_theo_tt, "don_khong_co_item_theo_trang_thai.csv")

kc = delivery_distance["average_distance_km"].dropna()
SUMMARY["khoang_cach"] = {
    "so_don_co": int(len(kc)), "so_don_thieu": int((~co_kc).sum()),
    "trung_binh": float(kc.mean()), "trung_vi": float(kc.median()), "min": float(kc.min()), "max": float(kc.max()),
    "so_don_duoi_1km": int((kc < 1).sum()), "phan_ra_thieu": phan_ra_kc.set_index("Lý do")["Số đơn"].to_dict(),
    "don_khong_co_item_theo_trang_thai": thieu_kc_theo_tt.set_index("Trạng thái")["Số đơn"].to_dict()}

# Độ nhạy: dùng trung vị tọa độ thay vì trung bình
so_ss = dist_mean.merge(dist_med, on="order_id", suffixes=("_tb", "_tv"))
lech = (so_ss["average_distance_km_tb"] - so_ss["average_distance_km_tv"]).abs()
SUMMARY["do_nhay_toa_do_trung_vi"] = {
    "so_don_so_sanh": int(len(so_ss)),
    "so_don_lech_tren_10km": int((lech > 10).sum()), "ty_le_lech_tren_10km_pct": float((lech > 10).mean() * 100),
    "lech_toi_da_km": float(lech.max()),
    "pearson_hai_cach": float(so_ss["average_distance_km_tb"].corr(so_ss["average_distance_km_tv"]))}

# ==============================================================================
# BƯỚC 6. 2.2.3 – KHOẢNG CÁCH, CƯỚC PHÍ, KHỐI LƯỢNG, ĐỘ TRỄ, THỜI GIAN GIAO
# ==============================================================================
tieu_de("BƯỚC 6: KHOẢNG CÁCH – CƯỚC PHÍ – ĐỘ TRỄ")
items = tables["order_items"].merge(tables["products"][["product_id", "product_weight_g"]],
                                    on="product_id", how="left", validate="many_to_one")
theo_don = items.groupby("order_id").agg(
    tong_cuoc_phi=("freight_value", "sum"), tong_gia=("price", "sum"),
    khoi_luong_g=("product_weight_g", "sum"), so_item_thieu_kl=("product_weight_g", lambda s: s.isna().sum())
).reset_index()
theo_don.loc[theo_don["so_item_thieu_kl"] > 0, "khoi_luong_g"] = np.nan

kc_cp = delivery_distance.merge(theo_don, on="order_id", how="left", validate="one_to_one")
du_lieu_cp = kc_cp[["average_distance_km", "tong_cuoc_phi"]].dropna()
n_cp = len(du_lieu_cp)
r_p = du_lieu_cp["average_distance_km"].corr(du_lieu_cp["tong_cuoc_phi"])
r_s = du_lieu_cp["average_distance_km"].corr(du_lieu_cp["tong_cuoc_phi"], method="spearman")


def partial_spearman(x, y, z):
    rx, ry, rz = (pd.Series(v).rank().to_numpy() for v in (x, y, z))
    A = np.c_[np.ones(len(rz)), rz]

    def phan_du(a):
        return a - A @ np.linalg.lstsq(A, a, rcond=None)[0]
    return float(np.corrcoef(phan_du(rx), phan_du(ry))[0, 1])


dl_kl = kc_cp[["average_distance_km", "tong_cuoc_phi", "khoi_luong_g"]].dropna()
dl_kl = dl_kl[dl_kl["khoi_luong_g"] > 0]
r_kl_cp = dl_kl["khoi_luong_g"].corr(dl_kl["tong_cuoc_phi"], method="spearman")
r_kc_kl = dl_kl["average_distance_km"].corr(dl_kl["khoi_luong_g"], method="spearman")
r_rieng = partial_spearman(dl_kl["average_distance_km"], dl_kl["tong_cuoc_phi"], dl_kl["khoi_luong_g"])

bang_tq_cp = pd.DataFrame({
    "Chi_tieu": [
        "Số đơn hàng đã có khoảng cách (trước khi ghép cước phí)",
        "Số đơn ghép được cước phí", "Số đơn đủ dữ liệu để tính tương quan",
        "Pearson (khoảng cách - cước phí)", "Spearman (khoảng cách - cước phí)",
        "Số đơn có đủ khối lượng (để kiểm soát)", "Spearman (khối lượng - cước phí)",
        "Spearman (khoảng cách - khối lượng)", "Spearman riêng phần (khoảng cách - cước phí | khối lượng)"],
    "Gia_tri": [int(co_kc.sum()), int(kc_cp["tong_cuoc_phi"].notna().sum()), n_cp, r_p, r_s,
                len(dl_kl), r_kl_cp, r_kc_kl, r_rieng]})
luu_bang(bang_tq_cp, "tuong_quan_khoang_cach_va_cuoc_phi.csv")
print(bang_tq_cp.to_string(index=False))
SUMMARY["tuong_quan_cuoc_phi"] = {"n": n_cp, "pearson": r_p, "spearman": r_s, "n_khoi_luong": len(dl_kl),
                                  "spearman_khoi_luong_cuoc_phi": r_kl_cp,
                                  "spearman_khoang_cach_khoi_luong": r_kc_kl, "spearman_rieng_phan": r_rieng}

# --- Hình 2.6 ---
p99_d, p99_f = du_lieu_cp["average_distance_km"].quantile(.99), du_lieu_cp["tong_cuoc_phi"].quantile(.99)
hien = du_lieu_cp[(du_lieu_cp["average_distance_km"] <= p99_d) & (du_lieu_cp["tong_cuoc_phi"] <= p99_f)]
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
hb = axes[0].hexbin(hien["average_distance_km"], hien["tong_cuoc_phi"], gridsize=55, bins="log",
                    cmap="Blues", mincnt=1)
hs = np.polyfit(hien["average_distance_km"], hien["tong_cuoc_phi"], 1)
xx = np.linspace(0, p99_d, 100)
axes[0].plot(xx, np.poly1d(hs)(xx), "r--", linewidth=2, label="Hồi quy tuyến tính (vùng hiển thị)")
axes[0].text(0.97, 0.05, f"Pearson r = {r_p:.3f}\nSpearman ρ = {r_s:.3f}\nn = {n_cp:,} (hiển thị ≤ P99)",
             transform=axes[0].transAxes, ha="right", fontsize=10,
             bbox=dict(boxstyle="round", fc="lightyellow", alpha=.9))
axes[0].set_title("(a) Khoảng cách và cước phí")
axes[0].set_xlabel("Khoảng cách trung bình khách hàng – người bán (km)")
axes[0].set_ylabel("Tổng cước phí vận chuyển của đơn (R$)")
axes[0].legend(loc="upper left", fontsize=9)
fig.colorbar(hb, ax=axes[0], label="Số đơn (thang log)")
kl_ve = dl_kl[(dl_kl["khoi_luong_g"] <= dl_kl["khoi_luong_g"].quantile(.99)) & (dl_kl["tong_cuoc_phi"] <= p99_f)]
hb2 = axes[1].hexbin(kl_ve["khoi_luong_g"] / 1000, kl_ve["tong_cuoc_phi"], gridsize=55, bins="log",
                     cmap="Oranges", mincnt=1)
axes[1].text(0.97, 0.05, f"Spearman (khối lượng – cước phí) = {r_kl_cp:.3f}\nRiêng phần (khoảng cách – cước phí | khối lượng) = {r_rieng:.3f}",
             transform=axes[1].transAxes, ha="right", fontsize=9.5,
             bbox=dict(boxstyle="round", fc="lightyellow", alpha=.9))
axes[1].set_title("(b) Khối lượng đơn hàng và cước phí")
axes[1].set_xlabel("Tổng khối lượng đơn hàng (kg)")
axes[1].set_ylabel("Tổng cước phí vận chuyển của đơn (R$)")
fig.colorbar(hb2, ax=axes[1], label="Số đơn (thang log)")
luu_hinh("hinh_2_6_khoang_cach_khoi_luong_cuoc_phi.png")

# --- Khoảng cách và độ trễ / thời gian giao ---
dat = delivery_distance.dropna(subset=["average_distance_km", "is_delayed"]).copy()
r_kc_tg_p = dat["average_distance_km"].corr(dat["tong_thoi_gian_giao_ngay"])
r_kc_tg_s = dat["average_distance_km"].corr(dat["tong_thoi_gian_giao_ngay"], method="spearman")
r_kc_dl_p = dat["average_distance_km"].corr(dat["delivery_delay_days"])
r_kc_dl_s = dat["average_distance_km"].corr(dat["delivery_delay_days"], method="spearman")
r_kc_ke = dat["average_distance_km"].corr(dat["thoi_gian_du_kien_ngay"], method="spearman")
bang_tq_tre = pd.DataFrame({
    "Chi_tieu": ["Số đơn đủ dữ liệu", "Pearson (khoảng cách - thời gian giao thực tế)",
                 "Spearman (khoảng cách - thời gian giao thực tế)",
                 "Spearman (khoảng cách - thời gian dự kiến)",
                 "Pearson (khoảng cách - số ngày chênh lệch so với dự kiến)",
                 "Spearman (khoảng cách - số ngày chênh lệch so với dự kiến)"],
    "Gia_tri": [len(dat), r_kc_tg_p, r_kc_tg_s, r_kc_ke, r_kc_dl_p, r_kc_dl_s]})
luu_bang(bang_tq_tre, "tuong_quan_khoang_cach_va_thoi_gian_giao.csv")
print(bang_tq_tre.to_string(index=False))
SUMMARY["tuong_quan_khoang_cach_thoi_gian"] = {
    "n": len(dat), "pearson_thoi_gian_giao": r_kc_tg_p, "spearman_thoi_gian_giao": r_kc_tg_s,
    "spearman_thoi_gian_du_kien": r_kc_ke, "pearson_delay": r_kc_dl_p, "spearman_delay": r_kc_dl_s}

bins_kc = [0, 250, 500, 1000, 2000, np.inf]
nhan_kc = ["Dưới 250 km", "250–500 km", "500–1.000 km", "1.000–2.000 km", "Từ 2.000 km"]
dat["nhom_kc"] = pd.cut(dat["average_distance_km"], bins=bins_kc, labels=nhan_kc, right=False, include_lowest=True)
bang_kc = dat.merge(theo_don[["order_id", "tong_cuoc_phi"]], on="order_id", how="left").groupby(
    "nhom_kc", observed=True).agg(
    total_orders=("order_id", "count"), delayed_orders=("is_delayed", "sum"),
    tb_thoi_gian_giao=("tong_thoi_gian_giao_ngay", "mean"), trung_vi_thoi_gian_giao=("tong_thoi_gian_giao_ngay", "median"),
    tb_thoi_gian_du_kien=("thoi_gian_du_kien_ngay", "mean"),
    average_delay_days=("delivery_delay_days", "mean"), average_distance_km=("average_distance_km", "mean"),
    trung_vi_cuoc_phi=("tong_cuoc_phi", "median")).reset_index()
bang_kc["delay_rate_percent"] = bang_kc["delayed_orders"] / bang_kc["total_orders"] * 100
luu_bang(bang_kc.round(2), "thong_ke_do_tre_theo_nhom_khoang_cach.csv")
print(bang_kc.round(2).to_string(index=False))

# Kiểm định xu hướng: tỷ lệ trễ có tăng theo nhóm khoảng cách không? (chi-bình phương)
ct = pd.crosstab(dat["nhom_kc"], dat["is_delayed"])
chi2, p_chi, _, _ = stats.chi2_contingency(ct)
SUMMARY["nhom_khoang_cach_chi2"] = {"chi2": float(chi2), "p": float(p_chi)}

# --- Hình 2.7 ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
b = axes[0].bar(bang_kc["nhom_kc"].astype(str), bang_kc["delay_rate_percent"], color=C_MAIN)
axes[0].axhline(SO_TRE / SO_DU_DK * 100, color=C_WARN, linestyle="--", label=f"Trung bình ({SO_TRE / SO_DU_DK * 100:.1f}%)")
for bb, r in zip(b, bang_kc.itertuples()):
    axes[0].text(bb.get_x() + bb.get_width() / 2, bb.get_height() + .2,
                 f"{r.delay_rate_percent:.1f}%\n(n={r.total_orders:,})", ha="center", fontsize=9)
axes[0].set_ylim(0, bang_kc["delay_rate_percent"].max() * 1.25)
axes[0].set_title("(a) Tỷ lệ giao trễ theo nhóm khoảng cách")
axes[0].set_xlabel("Nhóm khoảng cách khách hàng – người bán")
axes[0].set_ylabel("Tỷ lệ giao trễ (%)")
axes[0].tick_params(axis="x", rotation=20)
axes[0].legend()
x = np.arange(len(bang_kc))
axes[1].bar(x - .2, bang_kc["trung_vi_thoi_gian_giao"], .4, color=C_MAIN, label="Thực tế (trung vị)")
axes[1].bar(x + .2, bang_kc["tb_thoi_gian_du_kien"], .4, color=C_ORANGE, label="Dự kiến (trung bình)")
for i, r in enumerate(bang_kc.itertuples()):
    axes[1].text(i - .2, r.trung_vi_thoi_gian_giao + .3, f"{r.trung_vi_thoi_gian_giao:.1f}", ha="center", fontsize=9)
    axes[1].text(i + .2, r.tb_thoi_gian_du_kien + .3, f"{r.tb_thoi_gian_du_kien:.1f}", ha="center", fontsize=9)
axes[1].set_xticks(x)
axes[1].set_xticklabels(bang_kc["nhom_kc"].astype(str), rotation=20)
axes[1].set_title("(b) Thời gian giao thực tế và thời gian dự kiến (ngày)")
axes[1].set_xlabel("Nhóm khoảng cách khách hàng – người bán")
axes[1].set_ylabel("Số ngày kể từ lúc đặt hàng")
axes[1].legend()
luu_hinh("hinh_2_7_do_tre_va_thoi_gian_giao_theo_khoang_cach.png")

# --- Bang khách hàng ---
bang_bang = (orders_delivered.merge(tables["customers"][["customer_id", "customer_state"]], on="customer_id", how="left")
             .groupby("customer_state").agg(
    so_don_du_dieu_kien=("order_id", "nunique"), so_don_giao_tre=("is_delayed", "sum"),
    trung_vi_thoi_gian_giao=("tong_thoi_gian_giao_ngay", "median")).reset_index())
bang_bang["ty_le_giao_tre_pct"] = bang_bang["so_don_giao_tre"] / bang_bang["so_don_du_dieu_kien"] * 100
bang_bang["co_mau_nho"] = bang_bang["so_don_du_dieu_kien"] < NGUONG_BANG_NHO
bang_bang = bang_bang.sort_values("ty_le_giao_tre_pct", ascending=False).reset_index(drop=True)
luu_bang(bang_bang.round(2), "thong_ke_do_tre_theo_bang_khach_hang.csv")

fig, ax = plt.subplots(figsize=(11, 9))
bv = bang_bang.sort_values("ty_le_giao_tre_pct")
bars = ax.barh(bv["customer_state"], bv["ty_le_giao_tre_pct"],
               color=[C_GREY if m else C_MAIN for m in bv["co_mau_nho"]])
for b_, r in zip(bars, bv.itertuples()):
    ax.text(b_.get_width() + .3, b_.get_y() + b_.get_height() / 2,
            f"{r.ty_le_giao_tre_pct:.1f}%  (n={r.so_don_du_dieu_kien:,}; median {r.trung_vi_thoi_gian_giao:.0f} ngày)",
            va="center", fontsize=8.5)
ax.axvline(SO_TRE / SO_DU_DK * 100, color=C_WARN, linestyle="--", label="Trung bình toàn quốc")
ax.set_xlim(0, bv["ty_le_giao_tre_pct"].max() * 1.6)
ax.set_title("Tỷ lệ giao trễ theo bang của khách hàng")
ax.set_xlabel("Tỷ lệ giao trễ (%)")
ax.set_ylabel("Bang khách hàng")
ax.legend(handles=[Patch(color=C_MAIN, label=f"Bang có ≥ {NGUONG_BANG_NHO} đơn"),
                   Patch(color=C_GREY, label=f"Bang có < {NGUONG_BANG_NHO} đơn (cỡ mẫu nhỏ)"),
                   plt.Line2D([0], [0], color=C_WARN, linestyle="--", label="Trung bình toàn quốc")], loc="lower right")
luu_hinh("hinh_2_8_ty_le_giao_tre_theo_bang.png")

# ==============================================================================
# BƯỚC 7. 2.2.4 – GIAO TRỄ VÀ MỨC ĐỘ HÀI LÒNG
# ==============================================================================
tieu_de("BƯỚC 7: GIAO TRỄ VÀ MỨC ĐỘ HÀI LÒNG")
rv_ts = rv.copy()
rv_ts["review_answer_timestamp"] = pd.to_datetime(rv_ts["review_answer_timestamp"], errors="coerce")
rv_don = rv_ts.groupby("order_id").agg(review_score_tb=("review_score", "mean")).reset_index()
rv_moi_nhat = (rv_ts.sort_values("review_answer_timestamp").drop_duplicates("order_id", keep="last")
               [["order_id", "review_score"]].rename(columns={"review_score": "diem_moi_nhat"}))
hl = (orders_delivered[["order_id", "is_delayed", "delivery_delay_days"]]
      .merge(rv_don, on="order_id", how="left", validate="one_to_one")
      .merge(rv_moi_nhat, on="order_id", how="left", validate="one_to_one"))
so_co_rv = int(hl["review_score_tb"].notna().sum())
print(f"Đơn có review: {so_co_rv:,}/{SO_DU_DK:,} ({pct(so_co_rv, SO_DU_DK)}%)")
hl = hl.dropna(subset=["review_score_tb"])

bang_hl = hl.groupby("is_delayed").agg(so_don=("order_id", "count"),
                                       diem_danh_gia_trung_binh=("review_score_tb", "mean"),
                                       do_lech_chuan=("review_score_tb", "std"),
                                       trung_vi=("review_score_tb", "median")).reset_index()
bang_hl["is_delayed"] = bang_hl["is_delayed"].map({0: "Đúng hạn hoặc giao sớm", 1: "Giao trễ"})
luu_bang(bang_hl.round(3), "thong_ke_hai_long_theo_tinh_trang_giao.csv")
print(bang_hl.round(3).to_string(index=False))

a = hl.loc[hl["is_delayed"] == 0, "review_score_tb"]
b_ = hl.loc[hl["is_delayed"] == 1, "review_score_tb"]
t_stat, p_val = stats.ttest_ind(a, b_, equal_var=False)
u_stat, p_u = stats.mannwhitneyu(a, b_, alternative="two-sided")
sp = np.sqrt(((len(a) - 1) * a.var() + (len(b_) - 1) * b_.var()) / (len(a) + len(b_) - 2))
cohen_d = (a.mean() - b_.mean()) / sp
chenh_tb = a.mean() - b_.mean()
se = np.sqrt(a.var() / len(a) + b_.var() / len(b_))
ci = (chenh_tb - 1.96 * se, chenh_tb + 1.96 * se)
prob_sup = u_stat / (len(a) * len(b_))   # xác suất đơn đúng hạn có điểm cao hơn đơn trễ (CL effect size)
ket_qua_kd = pd.DataFrame([{
    "Ten_kiem_dinh": "Welch t-test", "So_quan_sat_dung_han": len(a), "So_quan_sat_giao_tre": len(b_),
    "Chenh_lech_diem_tb": chenh_tb, "KTC95_duoi": ci[0], "KTC95_tren": ci[1],
    "Gia_tri_t": t_stat, "Gia_tri_p": p_val, "Cohen_d": cohen_d,
    "Mann_Whitney_U": u_stat, "Mann_Whitney_p": p_u, "Xac_suat_uu_the": prob_sup}])
luu_bang(ket_qua_kd, "ket_qua_kiem_dinh_hai_long_theo_giao_tre.csv")
print(ket_qua_kd.T)

d_int = hl.dropna(subset=["diem_moi_nhat"]).copy()
d_int["nhom"] = d_int["is_delayed"].map({0: "Đúng hạn hoặc giao sớm", 1: "Giao trễ"})
phan_bo_diem = pd.crosstab(d_int["nhom"], d_int["diem_moi_nhat"].astype(int), normalize="index") * 100
luu_bang(phan_bo_diem.round(2).reset_index(), "phan_bo_diem_danh_gia_theo_tinh_trang_giao.csv")
ty_le_1_2 = {k: float((d_int.loc[d_int["nhom"] == k, "diem_moi_nhat"] <= 2).mean() * 100) for k in phan_bo_diem.index}
ty_le_5 = {k: float((d_int.loc[d_int["nhom"] == k, "diem_moi_nhat"] == 5).mean() * 100) for k in phan_bo_diem.index}

nhan_muc = ["Đúng hạn/sớm", "Trễ ≤ 3 ngày", "Trễ 3–7 ngày", "Trễ 7–14 ngày", "Trễ > 14 ngày"]
hl["muc_tre"] = pd.cut(hl["delivery_delay_days"], [-np.inf, 0, 3, 7, 14, np.inf], labels=nhan_muc)
bang_muc = hl.groupby("muc_tre", observed=True).agg(
    so_don=("order_id", "count"), diem_tb=("review_score_tb", "mean"),
    ty_le_1_2_sao=("diem_moi_nhat", lambda s: (s <= 2).mean() * 100)).reset_index()
luu_bang(bang_muc.round(3), "diem_danh_gia_theo_muc_do_tre.csv")
print(bang_muc.round(3).to_string(index=False))
SUMMARY["hai_long"] = {
    "so_don_co_review": so_co_rv, "ty_le_co_review_pct": pct(so_co_rv, SO_DU_DK),
    "tb_dung_han": float(a.mean()), "tb_tre": float(b_.mean()), "sd_dung_han": float(a.std()), "sd_tre": float(b_.std()),
    "chenh_lech": float(chenh_tb), "ktc95": [float(ci[0]), float(ci[1])], "t": float(t_stat), "p": float(p_val),
    "cohen_d": float(cohen_d), "mann_whitney_p": float(p_u), "xac_suat_uu_the": float(prob_sup),
    "ty_le_1_2_sao_pct": ty_le_1_2, "ty_le_5_sao_pct": ty_le_5,
    "theo_muc_tre": bang_muc.round(3).to_dict("records")}

# --- Hình 2.9 ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
mau_diem = {1: "#C53030", 2: "#ED8936", 3: "#ECC94B", 4: "#68D391", 5: "#2F855A"}
trai = np.zeros(len(phan_bo_diem))
thu_tu = ["Đúng hạn hoặc giao sớm", "Giao trễ"]
pb = phan_bo_diem.loc[thu_tu]
for diem in sorted(pb.columns):
    axes[0].barh(pb.index, pb[diem], left=trai, color=mau_diem[diem], label=f"{diem} sao")
    for i, (v, l) in enumerate(zip(pb[diem], trai)):
        if v >= 4:
            axes[0].text(l + v / 2, i, f"{v:.0f}%", ha="center", va="center", color="white" if diem in (1, 5) else "black", fontsize=10, fontweight="bold")
    trai = trai + pb[diem].to_numpy()
axes[0].set_xlim(0, 100)
axes[0].set_title("(a) Phân bố điểm đánh giá (điểm của review mới nhất mỗi đơn)")
axes[0].set_xlabel("Tỷ lệ đơn hàng (%)")
axes[0].set_ylabel("")
axes[0].legend(ncol=5, loc="upper center", bbox_to_anchor=(.5, -.15), fontsize=9)
cols = [C_OK] + [C_ORANGE] * 4
bb = axes[1].bar(bang_muc["muc_tre"].astype(str), bang_muc["diem_tb"], color=cols)
for b__, r in zip(bb, bang_muc.itertuples()):
    axes[1].text(b__.get_x() + b__.get_width() / 2, b__.get_height() + .05, f"{r.diem_tb:.2f}\n(n={r.so_don:,})", ha="center", fontsize=9)
axes[1].set_ylim(0, 5.3)
axes[1].set_title("(b) Điểm đánh giá trung bình theo mức độ trễ")
axes[1].set_xlabel("Mức độ giao trễ so với ngày dự kiến")
axes[1].set_ylabel("Điểm đánh giá trung bình (1–5)")
axes[1].tick_params(axis="x", rotation=15)
luu_hinh("hinh_2_9_diem_danh_gia_theo_tinh_trang_giao_hang.png")

# ==============================================================================
# BƯỚC 8. 2.3.1 – DỮ LIỆU KHUYẾT THIẾU
# ==============================================================================
tieu_de("BƯỚC 8: DỮ LIỆU KHUYẾT THIẾU")
dm = missing_only_df.copy()
dm["nhan"] = dm["Tên bảng"] + "." + dm["Tên cột"]
dm = dm.sort_values("Tỷ lệ thiếu (%)")
muc = [(50, "#C53030", "> 50% thiếu"), (10, C_ORANGE, "10 – 50% thiếu"), (1, C_MAIN, "1 – 10% thiếu"), (0, C_OK, "< 1% thiếu")]


def chon_mau(v):
    for nguong, m, _ in muc:
        if v > nguong:
            return m
    return muc[-1][1]


fig, ax = plt.subplots(figsize=(12, max(6, len(dm) * .45)))
bars = ax.barh(dm["nhan"], dm["Tỷ lệ thiếu (%)"], color=[chon_mau(v) for v in dm["Tỷ lệ thiếu (%)"]])
for b_, r in zip(bars, dm.itertuples()):
    ax.text(b_.get_width() + .8, b_.get_y() + b_.get_height() / 2,
            f"{r[4]:,} / {r[3]:,} ({r[5]:.2f}%)", va="center", fontsize=9)
ax.set_xlim(0, dm["Tỷ lệ thiếu (%)"].max() * 1.35)
ax.set_title("Tỷ lệ dữ liệu khuyết thiếu theo thuộc tính (chỉ hiển thị cột có giá trị thiếu)")
ax.set_xlabel("Tỷ lệ khuyết thiếu (%)")
ax.set_ylabel("")
ax.legend(handles=[Patch(color=m, label=t) for _, m, t in muc], loc="lower right", title="Mức độ thiếu")
luu_hinh("hinh_2_10_ty_le_du_lieu_khuyet_thieu.png")

# Ma trận thiếu mốc thời gian x trạng thái đơn (thay cho heatmap lấy mẫu ngẫu nhiên)
moc3 = ["order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date"]
thu_tu_tt = ["created", "approved", "invoiced", "processing", "shipped", "delivered", "canceled", "unavailable"]
rows = []
for s in thu_tu_tt:
    nhom = orders_dt[orders_dt["order_status"] == s]
    for m in moc3:
        rows.append({"Trạng thái": s, "Mốc thời gian": m, "Tổng số đơn": len(nhom),
                     "Số đơn thiếu mốc": int(nhom[m].isna().sum()),
                     "Tỷ lệ thiếu (%)": pct(int(nhom[m].isna().sum()), len(nhom))})
thieu_theo_tt = pd.DataFrame(rows)
luu_bang(thieu_theo_tt, "thieu_moc_theo_trang_thai.csv")
mt_pct = thieu_theo_tt.pivot(index="Trạng thái", columns="Mốc thời gian", values="Tỷ lệ thiếu (%)").loc[thu_tu_tt, moc3]
mt_n = thieu_theo_tt.pivot(index="Trạng thái", columns="Mốc thời gian", values="Số đơn thiếu mốc").loc[thu_tu_tt, moc3]
mt_tot = orders_dt["order_status"].value_counts().reindex(thu_tu_tt)
annot = mt_pct.copy().astype(object)
for r_ in mt_pct.index:
    for c_ in mt_pct.columns:
        v_ = mt_pct.loc[r_, c_]
        annot.loc[r_, c_] = f"{v_:.2f}%\n({int(mt_n.loc[r_, c_]):,})" if 0 < v_ < 0.1 else f"{v_:.1f}%\n({int(mt_n.loc[r_, c_]):,})"
fig, ax = plt.subplots(figsize=(10, 6.5))
sns.heatmap(mt_pct, annot=annot, fmt="", cmap="Reds", vmin=0, vmax=100, cbar_kws={"label": "Tỷ lệ thiếu (%)"}, ax=ax, linewidths=.5)
ax.set_yticklabels([f"{s} (n={mt_tot[s]:,})" for s in thu_tu_tt], rotation=0)
ax.set_xticklabels(["Duyệt đơn", "Bàn giao vận chuyển", "Giao khách"], rotation=0)
ax.set_title("Tỷ lệ thiếu các mốc thời gian theo trạng thái đơn hàng")
ax.set_xlabel("Mốc thời gian")
ax.set_ylabel("Trạng thái đơn hàng")
luu_hinh("hinh_2_11_thieu_moc_thoi_gian_theo_trang_thai.png")

# Đối chiếu 2.965 đơn thiếu ngày giao theo trạng thái
thieu_giao = (orders_dt[orders_dt["order_delivered_customer_date"].isna()]["order_status"]
              .value_counts().rename_axis("Trạng thái").reset_index(name="Số đơn thiếu ngày giao khách"))
thieu_giao["Tỷ lệ (%)"] = (thieu_giao["Số đơn thiếu ngày giao khách"] / thieu_giao["Số đơn thiếu ngày giao khách"].sum() * 100).round(2)
luu_bang(thieu_giao, "doi_chieu_thieu_ngay_giao_theo_trang_thai.csv")
print(thieu_giao.to_string(index=False))
dl = orders_dt[orders_dt["order_status"] == "delivered"]
SUMMARY["thieu_moc_theo_trang_thai"] = {
    "thieu_ngay_giao_theo_trang_thai": thieu_giao.set_index("Trạng thái")["Số đơn thiếu ngày giao khách"].to_dict(),
    "delivered_thieu_duyet": int(dl["order_approved_at"].isna().sum()),
    "delivered_thieu_ban_giao": int(dl["order_delivered_carrier_date"].isna().sum()),
    "delivered_thieu_giao_khach": int(dl["order_delivered_customer_date"].isna().sum()),
    "tong_delivered": int(len(dl)),
    "trang_thai_dang_xu_ly": int(orders_dt["order_status"].isin(["shipped", "invoiced", "processing", "created", "approved"]).sum())}

# ==============================================================================
# BƯỚC 9. 2.3.2 – CANCELED / UNAVAILABLE
# ==============================================================================
tieu_de("BƯỚC 9: ĐƠN CANCELED / UNAVAILABLE")
cu = orders_analysis[orders_analysis["order_status"].isin(["canceled", "unavailable"])].copy()
ket_qua = []
for tt_ in ["canceled", "unavailable"]:
    nhom = cu[cu["order_status"] == tt_]
    for cot in COT_THOI_GIAN:
        ket_qua.append({"Trạng thái": tt_, "Mốc thời gian": cot, "Tổng số đơn": len(nhom),
                        "Số đơn thiếu mốc này": int(nhom[cot].isna().sum()),
                        "Tỷ lệ thiếu (%)": pct(int(nhom[cot].isna().sum()), len(nhom))})
luu_bang(pd.DataFrame(ket_qua), "thieu_moc_thoi_gian_canceled_unavailable.csv")

co_duyet = cu["order_approved_at"].notna()
co_vc = cu["order_delivered_carrier_date"].notna()
co_giao = cu["order_delivered_customer_date"].notna()
cu["tien_trinh_xu_ly"] = np.select(
    [co_giao & ~co_vc, co_giao, co_vc, co_duyet],
    ["Có ngày giao khách nhưng thiếu ngày bàn giao vận chuyển",
     "Đã giao đến khách dù đơn ở trạng thái canceled/unavailable",
     "Đã bàn giao vận chuyển nhưng không hoàn tất giao hàng",
     "Đã duyệt đơn nhưng dừng lại trước khi vận chuyển"],
    default="Hủy/hết hàng trước khi duyệt đơn")
tong_tt = cu.groupby("order_status").size().rename("Tong_so_don_trang_thai")
tien_trinh = (cu.groupby(["order_status", "tien_trinh_xu_ly"]).size().reset_index(name="So_luong")
              .merge(tong_tt, on="order_status"))
tien_trinh["Ty_le_pct"] = (tien_trinh["So_luong"] / tien_trinh["Tong_so_don_trang_thai"] * 100).round(2)
luu_bang(tien_trinh, "tien_trinh_xu_ly_canceled_unavailable.csv")
print(tien_trinh.to_string(index=False))


def dau_hieu(row):
    dh = []
    if pd.notna(row["order_approved_at"]) and row["order_approved_at"] < row["order_purchase_timestamp"]:
        dh.append("Duyệt đơn trước khi đặt hàng")
    if pd.notna(row["order_approved_at"]) and pd.notna(row["order_delivered_carrier_date"]) \
            and row["order_delivered_carrier_date"] < row["order_approved_at"]:
        dh.append("Bàn giao vận chuyển trước khi duyệt đơn")
    if pd.notna(row["order_delivered_carrier_date"]) and pd.notna(row["order_delivered_customer_date"]) \
            and row["order_delivered_customer_date"] < row["order_delivered_carrier_date"]:
        dh.append("Giao khách trước khi bàn giao vận chuyển")
    if pd.notna(row["order_delivered_customer_date"]):
        dh.append(f"Có ngày giao khách dù trạng thái là {row['order_status']}")
    return "; ".join(dh) if dh else "Không phát hiện dấu hiệu cần kiểm tra"


cu["dau_hieu_can_kiem_tra"] = cu.apply(dau_hieu, axis=1)
cu["co_dau_hieu"] = cu["dau_hieu_can_kiem_tra"] != "Không phát hiện dấu hiệu cần kiểm tra"
tk_dh = cu.groupby("order_status")["co_dau_hieu"].agg(So_don_co_dau_hieu="sum", Tong_so_don="count").reset_index()
tk_dh["Ty_le_pct"] = (tk_dh["So_don_co_dau_hieu"] / tk_dh["Tong_so_don"] * 100).round(2)
luu_bang(tk_dh, "dau_hieu_can_kiem_tra_canceled_unavailable.csv")
chi_tiet_6 = cu[cu["co_dau_hieu"]]
luu_bang(chi_tiet_6[["order_id", "order_status", "tien_trinh_xu_ly", "dau_hieu_can_kiem_tra"] + COT_THOI_GIAN],
         "chi_tiet_don_canceled_can_kiem_tra.csv")
# Các đơn canceled có ngày giao: có review không, điểm bao nhiêu?
rv_6 = rv[rv["order_id"].isin(chi_tiet_6["order_id"])][["order_id", "review_score"]]
SUMMARY["canceled_co_ngay_giao"] = {"so_don": int(len(chi_tiet_6)),
                                    "so_don_co_du_5_moc": int(chi_tiet_6[COT_THOI_GIAN].notna().all(axis=1).sum()),
                                    "diem_review": rv_6["review_score"].tolist()}
print(SUMMARY["canceled_co_ngay_giao"])

# Các đơn không có sản phẩm (order_items) theo trạng thái -> liên quan canceled/unavailable
sp_trong = orders_dt[~orders_dt["order_id"].isin(tables["order_items"]["order_id"])]["order_status"].value_counts()
SUMMARY["don_khong_co_item"] = {"tong": int(sp_trong.sum()), "theo_trang_thai": sp_trong.to_dict()}

# ==============================================================================
# BƯỚC 10. 2.3.3 – OUTLIER VÀ PHÂN PHỐI LỆCH
# ==============================================================================
tieu_de("BƯỚC 10: OUTLIER (IQR) VÀ SKEWNESS")


def detect_outliers_iqr(series, ten_bien, tong_goc):
    s = series.dropna()
    q1, q3 = s.quantile(.25), s.quantile(.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    n_out = int(((s < lo) | (s > hi)).sum())
    n_cao = int((s > hi).sum())
    sk = s.skew()
    return {"Bien_so": ten_bien, "Tong_so_dong_goc": tong_goc, "So_dong_thieu_du_lieu": int(tong_goc - len(s)),
            "So_dong_hop_le": len(s), "Can_duoi": round(lo, 2), "Can_tren": round(hi, 2),
            "So_luong_outlier": n_out, "Ty_le_outlier_pct": round(n_out / len(s) * 100, 2),
            "Outlier_phia_tren": n_cao, "Outlier_phia_duoi": n_out - n_cao,
            "Trung_vi": round(s.median(), 2), "Trung_binh": round(s.mean(), 2), "Max": round(s.max(), 2),
            "Skewness": round(sk, 3),
            "Nhan_xet_phan_phoi": ("Lệch phải mạnh" if sk > 1 else "Lệch phải nhẹ" if sk > .5 else
                                   "Lệch trái mạnh" if sk < -1 else "Lệch trái nhẹ" if sk < -.5 else "Gần đối xứng")}


bien = [("Giá sản phẩm (R$, log)", "Giá sản phẩm (price)", tables["order_items"]["price"], True),
        ("Cước phí vận chuyển (R$, log)", "Cước phí (freight_value)", tables["order_items"]["freight_value"], True),
        ("Khối lượng sản phẩm (g, log)", "Khối lượng sản phẩm (product_weight_g)", tables["products"]["product_weight_g"], True),
        ("Số ngày chênh lệch so với dự kiến (ngày)", "Số ngày trễ giao (delivery_delay_days)", orders_analysis["delivery_delay_days"], False)]
bang_out = pd.DataFrame([detect_outliers_iqr(s, nb, len(s)) for _, nb, s, _ in bien])
luu_bang(bang_out, "bang_outlier_cac_bien_so.csv")
print(bang_out[["Bien_so", "So_luong_outlier", "Ty_le_outlier_pct", "Outlier_phia_tren", "Outlier_phia_duoi", "Skewness"]].to_string(index=False))
SUMMARY["outlier"] = bang_out.set_index("Bien_so").to_dict("index")

fig, axes = plt.subplots(2, 2, figsize=(13, 10))
for ax, (nhan_ve, _, s, dung_log), (_, dong) in zip(axes.flatten(), bien, bang_out.iterrows()):
    s = s.dropna()
    if dung_log:
        s = s[s > 0]
    sns.boxplot(y=s, ax=ax, color="#90CDF4", fliersize=1.5, flierprops=dict(alpha=.3))
    if dung_log:
        ax.set_yscale("log")
    ax.axhline(dong["Can_tren"], color=C_WARN, linestyle="--", linewidth=1)
    if dong["Can_duoi"] > (0 if dung_log else -1e9):
        ax.axhline(dong["Can_duoi"], color=C_WARN, linestyle="--", linewidth=1)
    ax.set_title(nhan_ve, fontsize=11)
    ax.set_ylabel("")
    ax.text(.98, .97,
            f"Median {dong['Trung_vi']:,.1f} | TB {dong['Trung_binh']:,.1f} | Max {dong['Max']:,.0f}\n"
            f"Outlier: {dong['So_luong_outlier']:,} ({dong['Ty_le_outlier_pct']:.1f}%)\n"
            f"Skewness = {dong['Skewness']:.2f}\nĐường đỏ nét đứt = ngưỡng IQR",
            transform=ax.transAxes, fontsize=8.5, va="top", ha="right",
            bbox=dict(boxstyle="round", fc="lightyellow", alpha=.85))
fig.suptitle("Phân phối và giá trị ngoại lệ của các biến số chính (hiển thị toàn bộ dữ liệu, không cắt phân vị)", fontweight="bold")
luu_hinh("hinh_2_12_phan_phoi_va_ngoai_le.png")

# ==============================================================================
# BƯỚC 11. 2.3.4 – CẤU TRÚC KHÔNG GIAN VÀ XUNG ĐỘT MÃ BƯU CHÍNH
# ==============================================================================
tieu_de("BƯỚC 11: XUNG ĐỘT MÃ BƯU CHÍNH")
nhieu = zip_stat[zip_stat["n_ban_ghi"] >= 2].copy()
nhieu["do_phan_tan_km"] = np.sqrt((nhieu["lat_std"] * 111) ** 2 +
                                  (nhieu["lng_std"] * 111 * np.cos(np.radians(nhieu["latitude"]))) ** 2)
ngoai = geo[(geo["geolocation_lat"] > LAT_MAX) | (geo["geolocation_lat"] < LAT_MIN)
            | (geo["geolocation_lng"] < LNG_MIN) | (geo["geolocation_lng"] > LNG_MAX)]
cl_tam = haversine_distance(zip_stat["latitude"], zip_stat["longitude"], zip_stat["lat_med"], zip_stat["lng_med"])
zip_geo = set(zip_stat["geolocation_zip_code_prefix"])
kh_thieu_zip = ~tables["customers"]["customer_zip_code_prefix"].isin(zip_geo)
nb_thieu_zip = ~tables["sellers"]["seller_zip_code_prefix"].isin(zip_geo)
don_kh_thieu = int(orders_dt["customer_id"].isin(tables["customers"].loc[kh_thieu_zip, "customer_id"]).sum())

xd = pd.DataFrame([
    ("Số bản ghi geolocation", len(geo_raw)),
    ("Số bản ghi trùng lặp hoàn toàn", int(geo_raw.duplicated().sum())),
    ("Tỷ lệ bản ghi trùng lặp (%)", round(geo_raw.duplicated().mean() * 100, 2)),
    ("Số mã bưu chính duy nhất", len(zip_stat)),
    ("Số bản ghi trung bình mỗi mã (trung vị)", float(zip_stat["n_ban_ghi"].median())),
    ("Số bản ghi nhiều nhất của một mã", int(zip_stat["n_ban_ghi"].max())),
    ("Số mã chỉ có 1 bản ghi", int((zip_stat["n_ban_ghi"] == 1).sum())),
    ("Số mã thuộc hơn 1 bang", int((zip_stat["n_bang"] > 1).sum())),
    ("Số mã có hơn 1 cách viết tên thành phố", int((zip_stat["n_ten_tp"] > 1).sum())),
    ("Số bản ghi có tọa độ ngoài lãnh thổ Brazil", len(ngoai)),
    ("Số mã bưu chính bị ảnh hưởng bởi tọa độ ngoài lãnh thổ", int(ngoai["geolocation_zip_code_prefix"].nunique())),
    ("Số mã có độ phân tán tọa độ > 10 km", int((nhieu["do_phan_tan_km"] > 10).sum())),
    ("Số mã có độ phân tán tọa độ > 50 km", int((nhieu["do_phan_tan_km"] > 50).sum())),
    ("Số mã có độ phân tán tọa độ > 100 km", int((nhieu["do_phan_tan_km"] > 100).sum())),
    ("Độ phân tán lớn nhất của một mã (km)", round(float(nhieu["do_phan_tan_km"].max()), 1)),
    ("Số mã có tọa độ trung bình lệch trung vị > 5 km", int((cl_tam > 5).sum())),
    ("Số mã bưu chính của khách hàng không có trong geolocation", int(kh_thieu_zip.sum())),
    ("Số đơn hàng bị ảnh hưởng (khách hàng thiếu tọa độ)", don_kh_thieu),
    ("Số mã bưu chính của người bán không có trong geolocation", int(nb_thieu_zip.sum())),
], columns=["Chỉ tiêu", "Giá trị"])
luu_bang(xd, "xung_dot_ma_buu_chinh.csv")
print(xd.to_string(index=False))
SUMMARY["xung_dot_geo"] = dict(zip(xd["Chỉ tiêu"], xd["Giá trị"]))

fig, axes = plt.subplots(1, 2, figsize=(14, 5.8))
axes[0].scatter(zip_stat["longitude"], zip_stat["latitude"], s=3, color=C_GREY, alpha=.6, label="Tọa độ đại diện (trung bình) của mã bưu chính")
axes[0].scatter(ngoai["geolocation_lng"], ngoai["geolocation_lat"], s=25, color=C_WARN, label=f"Bản ghi ngoài lãnh thổ Brazil (n={len(ngoai)})")
axes[0].add_patch(Rectangle((LNG_MIN, LAT_MIN), LNG_MAX - LNG_MIN, LAT_MAX - LAT_MIN, fill=False, edgecolor=C_MAIN, linestyle="--"))
axes[0].set_title("(a) Vị trí các mã bưu chính và bản ghi ngoài lãnh thổ")
axes[0].set_xlabel("Kinh độ")
axes[0].set_ylabel("Vĩ độ")
axes[0].legend(loc="upper right", fontsize=8.5)
vals = nhieu["do_phan_tan_km"].clip(lower=.01)
axes[1].hist(vals, bins=np.logspace(-2, np.log10(vals.max() * 1.1), 50), color=C_MAIN, alpha=.85)
axes[1].set_xscale("log")
for t in (10, 50):
    axes[1].axvline(t, color=C_WARN, linestyle="--")
    axes[1].text(t * 1.08, axes[1].get_ylim()[1] * .85, f"{t} km", color=C_WARN)
axes[1].set_title("(b) Độ phân tán tọa độ trong cùng một mã bưu chính")
axes[1].set_xlabel("Độ phân tán (km, thang logarit)")
axes[1].set_ylabel("Số mã bưu chính")
axes[1].yaxis.set_major_formatter(mticker.FuncFormatter(nghin))
luu_hinh("hinh_2_13_xung_dot_ma_buu_chinh.png")

# ==============================================================================
# BƯỚC 12. 2.3.5 – TOÀN VẸN THAM CHIẾU VÀ NHẤT QUÁN THỜI GIAN
# ==============================================================================
tieu_de("BƯỚC 12: TOÀN VẸN THAM CHIẾU")
t = tables
cat_tran = set(t["products"]["product_category_name"].dropna()) - set(t["category_translation"]["product_category_name"])
ri = pd.DataFrame([
    ("order_items.order_id", "orders.order_id", int((~t["order_items"]["order_id"].isin(t["orders"]["order_id"])).sum()), "Khóa ngoại"),
    ("order_items.product_id", "products.product_id", int((~t["order_items"]["product_id"].isin(t["products"]["product_id"])).sum()), "Khóa ngoại"),
    ("order_items.seller_id", "sellers.seller_id", int((~t["order_items"]["seller_id"].isin(t["sellers"]["seller_id"])).sum()), "Khóa ngoại"),
    ("orders.customer_id", "customers.customer_id", int((~t["orders"]["customer_id"].isin(t["customers"]["customer_id"])).sum()), "Khóa ngoại"),
    ("order_payments.order_id", "orders.order_id", int((~t["order_payments"]["order_id"].isin(t["orders"]["order_id"])).sum()), "Khóa ngoại"),
    ("order_reviews.order_id", "orders.order_id", int((~t["order_reviews"]["order_id"].isin(t["orders"]["order_id"])).sum()), "Khóa ngoại"),
    ("products.product_category_name", "category_translation", len(cat_tran), f"Danh mục thiếu bản dịch: {', '.join(sorted(cat_tran))}"),
    ("customers.customer_zip_code_prefix", "geolocation", int(kh_thieu_zip.sum()), "Mã bưu chính thiếu tọa độ"),
    ("sellers.seller_zip_code_prefix", "geolocation", int(nb_thieu_zip.sum()), "Mã bưu chính thiếu tọa độ"),
    ("orders (không có dòng order_items)", "order_items", int((~t["orders"]["order_id"].isin(t["order_items"]["order_id"])).sum()), "Đơn không có sản phẩm"),
    ("orders (không có dòng order_payments)", "order_payments", int((~t["orders"]["order_id"].isin(t["order_payments"]["order_id"])).sum()), "Đơn không có thanh toán"),
    ("orders (không có dòng order_reviews)", "order_reviews", int((~t["orders"]["order_id"].isin(t["order_reviews"]["order_id"])).sum()), "Đơn chưa có đánh giá"),
], columns=["Quan hệ kiểm tra (con)", "Bảng cha", "Số bản ghi vi phạm", "Ghi chú"])
luu_bang(ri, "bang_kiem_tra_toan_ven_tham_chieu.csv")
print(ri.to_string(index=False))
SUMMARY["toan_ven_tham_chieu"] = ri.set_index("Quan hệ kiểm tra (con)")["Số bản ghi vi phạm"].to_dict()

# Bảng nhất quán thời gian đã lưu ở BƯỚC 4 (canh_bao_thoi_gian_am_cac_chang.csv)
SUMMARY["nhat_quan_thoi_gian"] = bang_canh_bao.set_index("Chặng xử lý").to_dict("index")

# ==============================================================================
# KẾT THÚC: LƯU TỔNG HỢP SỐ LIỆU
# ==============================================================================
with open(TABLE_DIR / "tong_hop_so_lieu_chuong2.json", "w", encoding="utf-8") as f:
    json.dump(SUMMARY, f, ensure_ascii=False, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))

print("\n" + "=" * 70)
print("HOÀN TẤT CHƯƠNG 2: đã lưu bảng, 13 hình và tong_hop_so_lieu_chuong2.json")
print("=" * 70)
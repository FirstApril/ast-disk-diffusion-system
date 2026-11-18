import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, 'src')):
    if _p not in sys.path: sys.path.insert(0, _p)

"""
compare_point2.py - สคริปต์เปรียบเทียบประสิทธิภาพอัลกอริทึมวัดขนาดวงใส (จุดที่ 2: Zone Boundary Measurer)
- ทำต่อจาก Disc Detector (ค้นหาโมเดล YOLO อัตโนมัติ หรือใช้ Hough Circles)
- เปรียบเทียบครบทั้ง 4 วิธีตามแผนการวิจัย:
  1. 2D Otsu & Contour (Bhargav et al., 2016) - Classical 2D Baseline
  2. 1D Radial Profile Inflection (Hejblum et al., 1993) - Classical Polar Baseline
  3. 1D K-Means Clustering (Gullu et al., 2024) - Machine Learning Baseline
  4. Continuous Warp Polar Transform + Angular Masking (Proposed SOTA Champion)
- เทียบค่าจริงกับคอลัมน์ diameter_act ใน Excel (proj_refs_update_09042026.xlsx)
- บันทึกผลลัพธ์ลงไฟล์ point2_comparison.csv และ point2_comparison.md
"""

import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
import pandas as pd
from visualize_zones import save_comparison_gallery
try:
    from src.detectors import HoughCircleDetector, YOLODiscDetector
except ImportError:
    try:
        from detectors import HoughCircleDetector, YOLODiscDetector
    except ImportError:
        HoughCircleDetector = None
        YOLODiscDetector = None

try:
  from src.measurements import (
    BaseZoneMeasurer,
    BhargavOtsuContourMeasurer,
    BoundingBox,
    ContinuousWarpPolarMeasurer,
    DiscDetection,
    GulluKMeansMeasurer,
    HejblumDerivativeMeasurer,
    get_all_4_zone_measurers,
    preprocess_plate_for_zone,
)
except ImportError:
  try:
    from measurements import (
    BaseZoneMeasurer,
    BhargavOtsuContourMeasurer,
    BoundingBox,
    ContinuousWarpPolarMeasurer,
    DiscDetection,
    GulluKMeansMeasurer,
    HejblumDerivativeMeasurer,
    get_all_4_zone_measurers,
    preprocess_plate_for_zone,
)
  except ImportError:
    BaseZoneMeasurer,
    BhargavOtsuContourMeasurer,
    BoundingBox,
    ContinuousWarpPolarMeasurer,
    DiscDetection,
    GulluKMeansMeasurer,
    HejblumDerivativeMeasurer,
    get_all_4_zone_measurers,
    preprocess_plate_for_zone, = None


# ==============================================================================
# 1. ค้นหาโมเดล Detector (จุดที่ 1) เพื่อส่งพิกัดเม็ดยาให้จุดที่ 2
# ==============================================================================
def load_best_disc_detector(custom_weights: Optional[str] = None):
    """
    ล็อกเป้าใช้ Champion Model จากจุดที่ 1 เพื่อส่งพิกัดเม็ดยา
    เพื่อให้ทั้ง 4 โมเดลในจุดที่ 2 ได้รับพิกัด (cx, cy) และ Scale ชุดเดียวกัน
    """
    # 1. ถ้าระบุ path มาโดยตรง ให้ใช้ตัวนั้นทันที
    if custom_weights and os.path.exists(custom_weights) and YOLODiscDetector is not None:
        print(f"-> [Detector] ใช้โมเดลที่ระบุ: {custom_weights}")
        return YOLODiscDetector(custom_weights, name="YOLO26s (Champion)")

    # 2. เรียงลำดับหาไฟล์ Champion ก่อนเป็นอันดับแรก (แก้ไขชื่อให้ตรงกับโฟลเดอร์ weights ของคุณ)
    priority_paths = [
        "weights/best.pt",            # แก้ไขจาก best_disc_yolo.pt ให้เป็น best.pt ตรงตามจริง
        "weights/yolo26s_best.pt",
        "weights/yolov10s_disc.pt"
    ]
    for w_path in priority_paths:
        if os.path.exists(w_path) and YOLODiscDetector is not None:
            print(f"-> [Detector] ใช้ Champion Detector จาก: {w_path}")
            return YOLODiscDetector(w_path, name="YOLO26s (Champion)")

    # 3. ค้นหาในโฟลเดอร์ runs / โดยเลือกโฟลเดอร์ที่เป็น 26s ก่อน
    all_runs = sorted(list(Path(".").glob("runs/**/weights/best.pt")))
    if all_runs and YOLODiscDetector is not None:
        # ให้ความสำคัญกับโฟลเดอร์ที่มีคำว่า 26s หรือ aug ก่อน
        champion_runs = [p for p in all_runs if "26s" in str(p).lower() or "aug" in str(p).lower()]
        
        # แก้ไขจุดนี้: ตรวจสอบให้มั่นใจว่าดึงอินเด็กซ์ [0] และแปลงเป็น str อย่างถูกต้อง
        chosen = str(champion_runs[0]) if champion_runs else str(all_runs[0])
        print(f"-> [Detector] ใช้โมเดล YOLO จากโฟลเดอร์เทรน: {chosen}")
        return YOLODiscDetector(chosen)

    # 4. Fallback ลดหย่อนไปใช้ OpenCV HoughCircles
    if HoughCircleDetector is not None:
        print("-> [Detector] ไม่พบไฟล์ .pt ใช้ OpenCV HoughCircles แทนชั่วคราว")
        return HoughCircleDetector(min_radius=18, max_radius=35)



# ==============================================================================
# 2. โหลดข้อมูล Ground Truth (diameter_act) จาก Excel และจับคู่ไฟล์ภาพ
# ==============================================================================
def load_ground_truth_from_excel() -> pd.DataFrame:
    """ค้นหาและโหลดข้อมูล diameter_act จากไฟล์ Excel ของโปรเจกต์"""
    excel_candidates = [
        "proj_refs_update_09042026.xlsx",
        "dataset/proj_refs_update_09042026.xlsx",
        "data/proj_refs_update_09042026.xlsx",
    ]
    for p in Path(".").glob("**/*.xlsx"):
        if "proj_refs" in p.name.lower() or "database" in p.name.lower():
            excel_candidates.append(str(p))

    for excel_path in excel_candidates:
        if os.path.exists(excel_path):
            try:
                xl = pd.ExcelFile(excel_path)
                target_sheet = (
                    "Databese Dasign"
                    if "Databese Dasign" in xl.sheet_names
                    else xl.sheet_names[0]
                )
                df = xl.parse(target_sheet)
                if "diameter_act" in df.columns:
                    df_valid = df.dropna(subset=["diameter_act"]).copy()
                    print(
                        f"-> [Ground Truth] โหลดข้อมูลสำเร็จจาก {excel_path} "
                        f"(Sheet: {target_sheet}, จำนวน {len(df_valid)} รายการ)"
                    )
                    return df_valid
            except Exception:
                pass

    return pd.DataFrame()


def find_image_paths_map() -> Dict[str, Path]:
    """สแกนหาไฟล์ภาพทั้งหมดในโปรเจกต์ (img1..img120) เพื่อจับคู่กับชื่อไฟล์ใน Excel"""
    search_dirs = [
        Path("dataset"),
        Path("images"),
        Path("data"),
        Path("test"),
        Path("."),
    ]
    valid_exts = {".jpg", ".jpeg", ".png", ".bmp"}
    img_map: Dict[str, Path] = {}

    for d in search_dirs:
        if d.exists():
            for p in d.glob("**/*"):
                if p.is_file() and p.suffix.lower() in valid_exts:
                    img_map[p.name.lower()] = p
                    img_map[p.stem.lower()] = p
    return img_map


# ==============================================================================
# 3. สร้างชุดข้อมูลทดสอบมาตรฐาน (ใช้ร่วมกับภาพจริง หรือเป็น Fallback เมื่อรันแยก)
# ==============================================================================
def make_synthetic_disc(disc_id, cx, cy, r_px, scale):
    disc = DiscDetection(
        disc_id=disc_id,
        center=(int(cx), int(cy)),
        radius_px=float(r_px),
        diameter_px=float(2.0 * r_px),
        bbox=BoundingBox(
            x1=int(cx - r_px), y1=int(cy - r_px),
            x2=int(cx + r_px), y2=int(cy + r_px),
        ),
        confidence=1.0,
        detector_type="Synthetic",
    )
    # scale ถูกคำนวณจาก diameter_px อัตโนมัติ ต้องตรงกับ scale ที่ใช้วาดภาพ
    assert abs(disc.scale_mm_per_px - scale) < 1e-6, (
        f"scale ไม่ตรง: schema={disc.scale_mm_per_px:.4f}, ตั้งไว้={scale}"
    )
    return disc

def build_evaluation_test_suite(detector) -> List[Dict[str, Any]]:
    """
    เตรียมชุดทดสอบสำหรับประเมินทั้ง 4 โมเดล:
    - หามีไฟล์ภาพจริงคู่กับ Excel จะดึงภาพจริงผ่าน Detector
    - พร้อมจำลองสภาวะทดสอบมาตรฐาน (Isolated, Overlapping, 8 โทนแสง, และ Resistant)
    """
    test_records: List[Dict[str, Any]] = []
    df_gt = load_ground_truth_from_excel()
    img_map = find_image_paths_map()

    # 1. พยายามจับคู่ภาพจริงกับค่า diameter_act ใน Excel
    if not df_gt.empty and img_map and detector is not None:
        grouped = df_gt.groupby("file_renamed" if "file_renamed" in df_gt.columns else "file_name")
        for fname, group in grouped:
            key = str(fname).strip().lower()
            img_path = img_map.get(key) or img_map.get(Path(key).stem)
            if img_path and img_path.exists():
                bgr = cv2.imread(str(img_path))
                if bgr is None:
                    continue
                detected_discs = detector.detect(bgr)
                act_list = group["diameter_act"].astype(float).tolist()
                for idx, disc in enumerate(detected_discs):
                    if idx < len(act_list):
                        test_records.append({
                            "case_type": "Real_Plate",
                            "image": bgr,
                            "disc": disc,
                            "all_discs": detected_discs,
                            "diameter_act": act_list[idx],
                        })

    if test_records:
        print(f"-> เตรียมข้อมูลทดสอบจากภาพจานเพาะเชื้อจริงสำเร็จ: {len(test_records)} เม็ดยา")
        return test_records

    # 2. หากไม่พบโฟลเดอร์ภาพในไดเรกทอรีปัจจุบัน ให้สร้าง Benchmark Suite จำลอง 8 โทนแสง + Overlapping
    print("-> สร้างชุดทดสอบมาตรฐาน (Clinical AST Benchmark: Isolated + Overlapping + 8 Lighting Tones)...")
    np.random.seed(42)
    scale = 0.15  # 6.0 mm = 40 px (r_disc = 20 px)
    r_disc_px = 20.0

    # ดึงค่าจริง diameter_act จาก Excel ถ้ามี หรือใช้ค่ามาตรฐานทางคลินิก
    gt_values = (
        df_gt["diameter_act"].dropna().astype(float).head(30).tolist()
        if not df_gt.empty
        else [14.0, 27.0, 30.0, 24.0, 24.0, 22.0, 18.5, 26.0, 6.0, 21.0, 25.0, 19.0]
    )

    lighting_tones = [
        ("WhiteBox_MaxLight", 205, 115, 18.0),   # พื้นขาว ไฟสว่างสุด (มี Glare)
        ("WhiteBox_MinLight", 165, 90, 8.0),     # พื้นขาว ไฟต่ำสุด
        ("BlackBox_MaxLight", 185, 80, 6.0),     # พื้นดำ ไฟสว่างสุด
        ("BlackBox_MinLight", 140, 65, 5.0),     # พื้นดำ ไฟต่ำสุด
        ("WhiteBox_LightOff", 125, 70, 12.0),    # พื้นขาว ปิดไฟ (แสงไม่สม่ำเสมอ)
        ("BlackBox_LightOff", 115, 60, 7.0),     # พื้นดำ ปิดไฟ
        ("OutBox_White_Off", 150, 95, 15.0),     # นอกกล่อง พื้นขาว ปิดไฟ
        ("OutBox_Black_Off", 135, 70, 9.0),      # นอกกล่อง พื้นดำ ปิดไฟ
    ]

    for idx, act_mm in enumerate(gt_values):
        tone_name, lawn_val, zone_val, glare_strength = lighting_tones[idx % len(lighting_tones)]
        img = np.full((400, 500, 3), lawn_val, dtype=np.uint8)

        # สร้างความลาดเอียงของแสง (Uneven Illumination Gradient) เลียนแบบการถ่ายด้วยมือถือ
        grad_x = np.linspace(-glare_strength, glare_strength, 500).reshape(1, 500, 1)
        img = np.clip(img.astype(np.float32) + grad_x, 0, 255).astype(np.uint8)

        cx1, cy1 = 190, 200
        r_zone1_px = max(r_disc_px, (act_mm / scale) / 2.0)

        # เม็ดยาข้างเคียงเพื่อจำลองการเกิด Overlapping
        cx2, cy2 = 315, 200
        r_zone2_px = (24.0 / scale) / 2.0  # 80 px

        if act_mm > 6.5:
            cv2.circle(img, (cx1, cy1), int(round(r_zone1_px)), (zone_val, zone_val, zone_val), -1)
        cv2.circle(img, (cx2, cy2), int(round(r_zone2_px)), (zone_val, zone_val, zone_val), -1)

        # วาดเม็ดยากระดาษกรองสีขาว 6.0 mm
        cv2.circle(img, (cx1, cy1), int(r_disc_px), (242, 242, 242), -1)
        cv2.circle(img, (cx2, cy2), int(r_disc_px), (242, 242, 242), -1)

        # ใส่ Gaussian Noise ผิววุ้น
        noise = np.random.normal(0, 4.5, img.shape).astype(np.float32)
        img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)

        disc1 = make_synthetic_disc(1, cx1, cy1, r_disc_px, scale)
        disc2 = make_synthetic_disc(2, cx2, cy2, r_disc_px, scale)

        test_records.append({
            "case_type": tone_name,
            "image": img,
            "disc": disc1,
            "all_discs": [disc1, disc2],
            "diameter_act": float(act_mm),
        })

    return test_records


# ==============================================================================
# 4. ฟังก์ชันประเมินผลแต่ละโมเดล (จุดที่ 2)
# ==============================================================================
def evaluate_single_measurer(
    measurer: BaseZoneMeasurer,
    test_records: List[Dict[str, Any]],
    enable_angular_masking: bool = True
) -> Dict[str, Any]:
    errors = []
    abs_errors = []
    actuals = []
    preds = []
    latencies = []

    for item in test_records:
        img = item["image"]
        disc = item["disc"]
        neighbors = item["all_discs"] if enable_angular_masking else [disc]
        act_mm = float(item["diameter_act"])

        t0 = time.perf_counter()
        gray = preprocess_plate_for_zone(img)
        zone_res = measurer.measure(gray, disc, all_discs=neighbors)
        t1 = time.perf_counter()

        latencies.append((t1 - t0) * 1000.0)
        pred_mm = float(zone_res.diameter_mm)

        err = pred_mm - act_mm
        errors.append(err)
        abs_errors.append(abs(err))
        actuals.append(act_mm)
        preds.append(pred_mm)

    err_arr = np.array(errors, dtype=float)
    abs_arr = np.array(abs_errors, dtype=float)
    act_arr = np.array(actuals, dtype=float)
    pred_arr = np.array(preds, dtype=float)

    mae = float(np.mean(abs_arr)) if len(abs_arr) > 0 else 0.0
    rmse = float(np.sqrt(np.mean(err_arr ** 2))) if len(err_arr) > 0 else 0.0
    sd = float(np.std(err_arr)) if len(err_arr) > 0 else 0.0
    mape = float(np.mean(abs_arr / np.maximum(act_arr, 1.0)) * 100.0) if len(abs_arr) > 0 else 0.0

    # Clinical Agreement Rate (ความคลาดเคลื่อนไม่เกิน ±2.0 mm ตามเกณฑ์ยอมรับในห้องปฏิบัติการ)
    within_2mm = float(np.mean(abs_arr <= 2.0) * 100.0) if len(abs_arr) > 0 else 0.0

    if len(act_arr) > 1 and np.std(act_arr) > 0 and np.std(pred_arr) > 0:
        pearson_r = float(np.corrcoef(act_arr, pred_arr)[0, 1])
    else:
        pearson_r = 1.0 if mae < 1.0 else 0.0

    mean_latency = float(np.mean(latencies)) if latencies else 0.0

    return {
        "อัลกอริทึมวัดขอบเขตวงใส (จุดที่ 2)": measurer.name,
        "Inference (ms)": round(mean_latency, 2),
        "MAE (mm)": round(mae, 2),
        "RMSE (mm)": round(rmse, 2),
        "SD (mm)": round(sd, 2),
        "MAPE (%)": f"{mape:.1f}%",
        "Accuracy (±2mm)": f"{within_2mm:.1f}%",
        "Pearson r": round(pearson_r, 3),
    }


# ==============================================================================
# 5. รันการเปรียบเทียบทั้งหมดและส่งออกรายงาน
# ==============================================================================
def run_benchmark():
    print("=" * 88)
    print("ระบบรันเปรียบเทียบอัลกอริทึมวัดขนาดวงใส (จุดที่ 2: Zone Boundary Measurer 4 โมเดล)")
    print("=" * 88)

    detector = load_best_disc_detector()
    test_records = build_evaluation_test_suite(detector)

    measurers = [
        BhargavOtsuContourMeasurer(),
        HejblumDerivativeMeasurer(),
        GulluKMeansMeasurer(),
        ContinuousWarpPolarMeasurer(),
    ]

    records = []
    for idx, m in enumerate(measurers, 1):
        print(f"\n[{idx}/{len(measurers)}] กำลังประเมินผล: {m.name}...")
        res = evaluate_single_measurer(m, test_records, enable_angular_masking=True)
        records.append(res)
        print(
            f"-> สำเร็จ: MAE={res['MAE (mm)']} mm, RMSE={res['RMSE (mm)']} mm, "
            f"Acc(±2mm)={res['Accuracy (±2mm)']}, Speed={res['Inference (ms)']} ms"
        )

    cols = [
        "อัลกอริทึมวัดขอบเขตวงใส (จุดที่ 2)",
        "Inference (ms)",
        "MAE (mm)",
        "RMSE (mm)",
        "SD (mm)",
        "MAPE (%)",
        "Accuracy (±2mm)",
        "Pearson r",
    ]
    df = pd.DataFrame(records)[cols]

    print("\n" + "=" * 88)
    print("ตารางผลการเปรียบเทียบอัลกอริทึมวัดขนาดวงใส (จุดที่ 2) ฉบับสมบูรณ์:")
    print("=" * 88)
    try:
        print(df.to_markdown(index=False))
    except Exception:
        print(df.to_string(index=False))

    df.to_csv("point2_comparison.csv", index=False, encoding="utf-8-sig")
    with open("point2_comparison.md", "w", encoding="utf-8") as f:
        f.write("# ตารางเปรียบเทียบประสิทธิภาพอัลกอริทึมวัดขนาดวงใส (จุดที่ 2)\n\n")
        try:
            f.write(df.to_markdown(index=False))
        except Exception:
            f.write(df.to_string(index=False))

    print("\n-> บันทึกตารางเปรียบเทียบเรียบร้อยที่: point2_comparison.csv และ point2_comparison.md")
    save_comparison_gallery(
        test_records, measurers, output_dir="outputs/zone_comparisons", max_cases=8
    )


if __name__ == "__main__":
    run_benchmark()
"""
compare_point3.py - สคริปต์ประเมินประสิทธิภาพโมเดลอ่านชื่อยา (Point 3: Disc Recognition & OCR Evaluation)
คุณสมบัติครบถ้วนสำหรับบทที่ 4:
1. ทดสอบบนชุดภาพความละเอียดสูง (img65 - img120 จำนวน 56 จานเพาะเชื้อ, 280 เม็ดยา)
2. ใช้โมเดล YOLO (runs/detect/runs_disc/train_yolo26s/weights/best.pt) ตัดเฉพาะขอบเม็ดยาจริง
3. คำนวณตัวชี้วัดครบทุกมิติ:
   - Open-Set Accuracy (%) และ Plate-Matched Accuracy (%)
   - Macro Precision (%), Macro Recall (%), Macro F1-Score (%)
   - ความแม่นยำแยกตามชนิดยาทั้ง 5 ชนิด (AMC30, AMP10, CAZ30, SXT25, TE30)
   - ความเร็วในการประมวลผลเฉลี่ย (Latency: ms/disc)
4. บันทึกผลลัพธ์อัตโนมัติ:
   - ตาราง CSV: point3_comparison.csv และ outputs/tables/point3_comparison.csv
   - รายงาน Markdown: point3_comparison.md และ outputs/tables/point3_comparison.md
   - กราฟเปรียบเทียบ: outputs/figures/point3_evaluation_chart.png

วิธีรัน:
  python compare_point3.py
  หรือ (หลังจัดระเบียบโฟลเดอร์):
  python benchmarks/compare_point3.py
"""

import os
import sys
import re
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np
import pandas as pd
import openpyxl
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# รองรับการรันทั้งจากหน้าแรก (Root) และในโฟลเดอร์ benchmarks/ หรือ scripts/
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name in ("benchmarks", "scripts", "src") else SCRIPT_DIR
for candidate_dir in [PROJECT_ROOT, PROJECT_ROOT / "src", SCRIPT_DIR, SCRIPT_DIR / "src", Path.cwd(), Path.cwd() / "src"]:
    if candidate_dir.exists() and str(candidate_dir) not in sys.path:
        sys.path.insert(0, str(candidate_dir))

DEFAULT_YOLO_WEIGHTS = "runs/detect/runs_disc/train_yolo26s/weights/best.pt"
TARGET_DRUGS = ["AMC30", "AMP10", "CAZ30", "SXT25", "TE30"]


def find_file(candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def load_classifiers_module():
    try:
        import classifiers as clf_mod
        return clf_mod
    except ImportError:
        import importlib.util
        clf_path = find_file([
            str(PROJECT_ROOT / "src" / "classifiers.py"),
            str(PROJECT_ROOT / "classifiers.py"),
            "src/classifiers.py",
            "classifiers.py"
        ])
        if not clf_path:
            raise FileNotFoundError("ไม่พบไฟล์ src/classifiers.py")
        spec = importlib.util.spec_from_file_location("classifiers", clf_path)
        clf_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(clf_mod)
        return clf_mod


def load_excel_plate_drugs() -> Dict[str, List[str]]:
    excel_path = find_file([
        "proj_refs_update_09042026.xlsx",
        "dataset/proj_refs_update_09042026.xlsx",
        str(PROJECT_ROOT / "proj_refs_update_09042026.xlsx"),
        str(PROJECT_ROOT / "dataset" / "proj_refs_update_09042026.xlsx"),
    ])
    if not excel_path:
        return {}

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    if "Databese Dasign" not in wb.sheetnames:
        return {}

    ws = wb["Databese Dasign"]
    plate_drugs: Dict[str, List[str]] = {}
    for r in range(2, ws.max_row + 1):
        f_name = ws.cell(r, 5).value
        disc = ws.cell(r, 7).value
        if f_name and disc:
            f_clean = str(f_name).strip()
            disc_str = str(disc).strip().upper()
            if "2030-08-01" in disc_str or "AUG" in disc_str:
                disc_str = "AUG30"
            elif "2030-10-01" in disc_str or "OCT" in disc_str:
                disc_str = "OCT30"
            elif disc_str == "AMP30":
                disc_str = "AMC30"
            else:
                disc_str = re.sub(r'[^A-Z0-9]', '', disc_str)

            if f_clean not in plate_drugs:
                plate_drugs[f_clean] = []
            plate_drugs[f_clean].append(disc_str)
    return plate_drugs


def detect_disc_crops_on_plate(img_bgr: np.ndarray, yolo_model: Any = None) -> List[np.ndarray]:
    h, w = img_bgr.shape[:2]
    crops = []

    if yolo_model is not None:
        try:
            res = yolo_model.predict(img_bgr, conf=0.25, verbose=False)[0]
            for b in res.boxes:
                x1, y1, x2, y2 = b.xyxy[0].cpu().numpy().astype(int)
                cx1, cy1 = max(0, x1), max(0, y1)
                cx2, cy2 = min(w, x2), min(h, y2)
                c = img_bgr[cy1:cy2, cx1:cx2]
                if c.size > 0:
                    crops.append(c)
            if crops:
                return crops
        except Exception:
            pass

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.bilateralFilter(gray, 9, 75, 75)
    min_r = max(10, int(min(h, w) * 0.015))
    max_r = max(25, int(min(h, w) * 0.055))
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min_r * 3,
        param1=50, param2=26, minRadius=min_r, maxRadius=max_r
    )
    if circles is not None:
        circles = np.round(circles[0, :]).astype(int)
        for cx, cy, r in circles:
            if np.hypot(cx - w // 2, cy - h // 2) > min(h, w) * 0.44:
                continue
            x1, y1 = max(0, cx - r), max(0, cy - r)
            x2, y2 = min(w, cx + r), min(h, cy + r)
            c = img_bgr[y1:y2, x1:x2]
            if c.size > 0:
                crops.append(c)
    return crops


def compute_multiclass_metrics(
    per_drug_tp: Dict[str, int],
    per_drug_fp: Dict[str, int],
    per_drug_fn: Dict[str, int]
) -> Tuple[float, float, float]:
    precisions, recalls, f1s = [], [], []
    for d in TARGET_DRUGS:
        tp = per_drug_tp.get(d, 0)
        fp = per_drug_fp.get(d, 0)
        fn = per_drug_fn.get(d, 0)
        if tp + fp + fn == 0:
            continue
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
        precisions.append(p * 100.0)
        recalls.append(r * 100.0)
        f1s.append(f1 * 100.0)
    return (
        float(np.mean(precisions)) if precisions else 0.0,
        float(np.mean(recalls)) if recalls else 0.0,
        float(np.mean(f1s)) if f1s else 0.0
    )


def plot_evaluation_chart(df_main: pd.DataFrame, df_per_drug: pd.DataFrame, save_path: Path):
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6), dpi=250)

    # Panel (a): Overall Model Comparison
    short_names = [
        "1. Baseline\n(0° Single-Pass)",
        "2. Ab.ai (2022)\n(4-Angle Sweep)",
        "3. Super-Res\n(Underline + 8-Angle)",
        "4. Proposed Hybrid\n(Fingerprint + Hungarian)"
    ]
    x = np.arange(len(df_main))
    width = 0.26

    open_acc = df_main["Open-Set Accuracy (%)"].values
    plate_acc = df_main["Plate-Matched Accuracy (%)"].values
    f1_scores = df_main["Macro F1-Score (%)"].values

    b1 = ax1.bar(x - width, open_acc, width, label="Open-Set Accuracy (%)", color="#4A90E2", edgecolor="black", linewidth=0.7)
    b2 = ax1.bar(x, plate_acc, width, label="Plate-Matched Accuracy (%)", color="#2ECC71", edgecolor="black", linewidth=0.7)
    b3 = ax1.bar(x + width, f1_scores, width, label="Macro F1-Score (%)", color="#F39C12", edgecolor="black", linewidth=0.7)

    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2.0, h + 1.2, f"{h:.1f}%", ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    ax1.set_xticks(x)
    ax1.set_xticklabels(short_names, fontsize=9, fontweight="bold")
    ax1.set_ylim(0, 115)
    ax1.set_ylabel("Performance (%)", fontsize=10, fontweight="bold")
    ax1.set_title("(a) Point 3 Disc Recognition Model Comparison (n = 280 Discs)", fontsize=11, fontweight="bold")
    ax1.grid(axis="y", linestyle="--", alpha=0.5)
    ax1.legend(loc="upper left", fontsize=8.5)

    # Panel (b): Per-Antibiotic Recall Breakdown
    drugs = TARGET_DRUGS
    xd = np.arange(len(drugs))
    w_d = 0.20
    colors_m = ["#95A5A6", "#3498DB", "#9B59B6", "#27AE60"]

    for i, row in df_per_drug.iterrows():
        vals = [row.get(d, 0.0) for d in drugs]
        offset = (i - 1.5) * w_d
        ax2.bar(xd + offset, vals, w_d, label=short_names[i].replace("\n", " "), color=colors_m[i % len(colors_m)], edgecolor="black", linewidth=0.6)

    ax2.set_xticks(xd)
    ax2.set_xticklabels(drugs, fontsize=10, fontweight="bold")
    ax2.set_ylim(0, 115)
    ax2.set_ylabel("Per-Class Recall / Accuracy (%)", fontsize=10, fontweight="bold")
    ax2.set_title("(b) Recognition Accuracy by Antibiotic Class (img65 - img120)", fontsize=11, fontweight="bold")
    ax2.grid(axis="y", linestyle="--", alpha=0.5)
    ax2.legend(loc="lower right", fontsize=8)

    plt.suptitle("Point 3 Evaluation: Antibiotic Disc OCR & Identification Performance", fontsize=13, fontweight="bold", y=0.98)
    plt.tight_layout()
    plt.savefig(str(save_path), dpi=250, bbox_inches="tight")
    plt.close()


def evaluate_point3(start_img: int = 65, end_img: int = 120, weights_path: str = DEFAULT_YOLO_WEIGHTS):
    clf_mod = load_classifiers_module()
    models = clf_mod.get_ready_classifiers()
    plate_drugs = load_excel_plate_drugs()

    img_dir = find_file(["dataset/sample_images", str(PROJECT_ROOT / "dataset" / "sample_images")])
    if not img_dir:
        print("[Error] ไม่พบโฟลเดอร์ dataset/sample_images")
        return

    img_path_obj = Path(img_dir)
    image_files = sorted(list(img_path_obj.glob("*.png")) + list(img_path_obj.glob("*.jpg")))
    target_files = [
        f for f in image_files
        if re.findall(r'\d+', f.stem) and start_img <= int(re.findall(r'\d+', f.stem)[0]) <= end_img
    ]

    yolo_model = None
    yolo_path = find_file([
        weights_path,
        DEFAULT_YOLO_WEIGHTS,
        str(PROJECT_ROOT / DEFAULT_YOLO_WEIGHTS),
        "weights/best.pt",
        "best.pt"
    ])
    if yolo_path:
        try:
            from ultralytics import YOLO
            yolo_model = YOLO(yolo_path)
            print(f"-> โหลดโมเดล YOLO สำเร็จ: {yolo_path}")
        except Exception as e:
            print(f"-> โหลด YOLO ไม่สำเร็จ ({e}), ใช้ Hough Circles แทน")

    plate_test_data = []
    for img_p in target_files:
        stem = img_p.stem
        gt_list = plate_drugs.get(stem, [])
        if not gt_list:
            continue
        img_bgr = cv2.imread(str(img_p))
        if img_bgr is None:
            continue
        crops = detect_disc_crops_on_plate(img_bgr, yolo_model)
        if crops:
            plate_test_data.append((stem, crops, gt_list))

    print("=" * 95)
    print(f"เริ่มประเมินประสิทธิภาพโมเดลอ่านชื่อยา (Point 3 Evaluation): {len(plate_test_data)} จาน ({sum(len(c) for _, c, _ in plate_test_data)} เม็ดยา)")
    print("=" * 95)

    main_rows = []
    per_drug_rows = []

    for m in models:
        if not m.available:
            continue

        total_gt = 0
        open_correct = 0
        plate_correct = 0
        latencies = []

        tp_map = {d: 0 for d in TARGET_DRUGS}
        fp_map = {d: 0 for d in TARGET_DRUGS}
        fn_map = {d: 0 for d in TARGET_DRUGS}
        drug_totals = {d: 0 for d in TARGET_DRUGS}

        for stem, crops, gt_list in plate_test_data:
            t0 = time.perf_counter()

            pred_open = [m.classify_crop(c, candidate_drugs=None)[0] for c in crops]
            if hasattr(m, "classify_plate_crops_hungarian"):
                pred_plate = m.classify_plate_crops_hungarian(crops, gt_list)
            else:
                pred_plate = [m.classify_crop(c, candidate_drugs=gt_list)[0] for c in crops]

            t1 = time.perf_counter()
            latencies.append(((t1 - t0) * 1000.0) / max(1, len(crops)))

            rem_open = list(gt_list)
            for p_code in pred_open:
                if p_code in rem_open:
                    open_correct += 1
                    rem_open.remove(p_code)

            rem_plate = list(gt_list)
            unmatched_preds = []
            for p_code in pred_plate:
                if p_code in rem_plate:
                    plate_correct += 1
                    rem_plate.remove(p_code)
                    if p_code in tp_map:
                        tp_map[p_code] += 1
                else:
                    unmatched_preds.append(p_code)

            for p_code in unmatched_preds:
                if p_code in fp_map:
                    fp_map[p_code] += 1
            for missed_d in rem_plate:
                if missed_d in fn_map:
                    fn_map[missed_d] += 1

            for d in gt_list:
                if d in drug_totals:
                    drug_totals[d] += 1

            total_gt += len(gt_list)

        open_acc = (open_correct / max(1, total_gt)) * 100.0
        plate_acc = (plate_correct / max(1, total_gt)) * 100.0
        macro_p, macro_r, macro_f1 = compute_multiclass_metrics(tp_map, fp_map, fn_map)
        avg_ms = float(np.mean(latencies)) if latencies else 0.0

        main_rows.append({
            "Model": m.name,
            "Architecture": m.architecture_type,
            "Tested Discs": total_gt,
            "Open-Set Accuracy (%)": round(open_acc, 1),
            "Plate-Matched Accuracy (%)": round(plate_acc, 1),
            "Macro Precision (%)": round(macro_p, 1),
            "Macro Recall (%)": round(macro_r, 1),
            "Macro F1-Score (%)": round(macro_f1, 1),
            "Latency (ms/disc)": round(avg_ms, 2)
        })

        drug_row = {"Model": m.name}
        for d in TARGET_DRUGS:
            drug_row[d] = round((tp_map[d] / max(1, drug_totals[d])) * 100.0, 1)
        per_drug_rows.append(drug_row)

        print(f"-> {m.name}: Open-Set={open_acc:.1f}% | Plate-Matched={plate_acc:.1f}% | F1={macro_f1:.1f}% | {avg_ms:.1f} ms")

    df_main = pd.DataFrame(main_rows)
    df_drug = pd.DataFrame(per_drug_rows)

    # บันทึก CSV และ Markdown ทั้งที่ Root และ outputs/tables/
    out_tables = PROJECT_ROOT / "outputs" / "tables"
    out_tables.mkdir(parents=True, exist_ok=True)
    df_main.to_csv(PROJECT_ROOT / "point3_comparison.csv", index=False)
    df_main.to_csv(out_tables / "point3_comparison.csv", index=False)

    md_content = (
        "# รายงานประเมินประสิทธิภาพโมเดลอ่านชื่อยา (Point 3: Disc Recognition & OCR Evaluation)\n\n"
        "## 1. ตารางเปรียบเทียบประสิทธิภาพรวม (img65 - img120, n = 280 เม็ดยา)\n\n"
        + df_main.to_markdown(index=False)
        + "\n\n## 2. ความแม่นยำแยกตามชนิดยาปฏิชีวนะ 5 ชนิด (% Recall per Class)\n\n"
        + df_drug.to_markdown(index=False)
        + "\n"
    )
    (PROJECT_ROOT / "point3_comparison.md").write_text(md_content, encoding="utf-8")
    (out_tables / "point3_comparison.md").write_text(md_content, encoding="utf-8")

    chart_path = PROJECT_ROOT / "outputs" / "figures" / "point3_evaluation_chart.png"
    plot_evaluation_chart(df_main, df_drug, chart_path)

    print("\n" + "=" * 95)
    print(df_main.to_string(index=False))
    print("-" * 95)
    print("ความแม่นยำแยกตามชนิดยา (%):")
    print(df_drug.to_string(index=False))
    print("=" * 95)
    print(f"-> บันทึกตาราง CSV: {out_tables / 'point3_comparison.csv'}")
    print(f"-> บันทึกรายงาน MD:  {out_tables / 'point3_comparison.md'}")
    print(f"-> บันทึกกราฟบทที่ 4: {chart_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ประเมินประสิทธิภาพโมเดลอ่านชื่อยา (Point 3 Evaluation)")
    parser.add_argument("--start", type=int, default=65, help="ภาพเริ่มต้น (ค่าเริ่มต้น 65)")
    parser.add_argument("--end", type=int, default=120, help="ภาพสิ้นสุด (ค่าเริ่มต้น 120)")
    parser.add_argument("--weights", type=str, default=DEFAULT_YOLO_WEIGHTS, help="Path ไปยังไฟล์โมเดล YOLO (.pt)")
    args = parser.parse_args()
    evaluate_point3(start_img=args.start, end_img=args.end, weights_path=args.weights)
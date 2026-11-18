"""
drug_reader.py - สคริปต์ทดสอบและเปรียบเทียบโมเดลอ่านชื่อยาทั้ง 4 รูปแบบ (Point 3 OCR Benchmark) บนภาพจริง
คุณสมบัติ:
1. ใช้โมเดล YOLO น้ำหนัก 'runs/detect/runs_disc/train_yolo26s/weights/best.pt' เป็นค่าเริ่มต้นตามที่ระบุ
2. เลือกทดสอบเฉพาะชุดภาพความละเอียดสูง (img65 ถึง img120) ถ่ายจากกล้องมือถือ Vivo X300 Pro (56 จานเพาะเชื้อ)
3. รันเปรียบเทียบครบทั้ง 4 โมเดล (Single-Pass, Ab.ai 4-Angle, Super-Res 8-Angle, Proposed Hybrid Hungarian)
4. แก้ Typo ในชีท Excel (AMP30 -> AMC30) อัตโนมัติ และบันทึกผลลง 'point3_comparison.csv' ทันที

วิธีสั่งรัน:
  python src/drug_reader.py --start 65 --end 120
"""

import os
import re
import sys
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import cv2
import numpy as np
import pandas as pd
import openpyxl

DEFAULT_YOLO_WEIGHTS = "runs/detect/runs_disc/train_yolo26s/weights/best.pt"

try:
    from classifiers import (
        EasyOCRSinglePassClassifier,
        EasyOCRStandardClassifier,
        EasyOCREnhancedClassifier,
        HybridHungarianASTClassifier,
        get_ready_classifiers,
        parse_and_match_drug,
        STANDARD_ANTIBIOTIC_CLASSES,
        ANTIBIOTIC_FULL_NAMES
    )
except ImportError:
    import importlib.util
    spec = importlib.util.spec_from_file_location('classifiers', os.path.join(os.path.dirname(__file__), 'classifiers.py'))
    clf_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clf_mod)
    EasyOCRSinglePassClassifier = clf_mod.EasyOCRSinglePassClassifier
    EasyOCRStandardClassifier = clf_mod.EasyOCRStandardClassifier
    EasyOCREnhancedClassifier = clf_mod.EasyOCREnhancedClassifier
    HybridHungarianASTClassifier = clf_mod.HybridHungarianASTClassifier
    get_ready_classifiers = clf_mod.get_ready_classifiers
    parse_and_match_drug = clf_mod.parse_and_match_drug
    STANDARD_ANTIBIOTIC_CLASSES = clf_mod.STANDARD_ANTIBIOTIC_CLASSES
    ANTIBIOTIC_FULL_NAMES = clf_mod.ANTIBIOTIC_FULL_NAMES


class DiscDrugReader:
    """คลาสหลักสำหรับเรียกใช้งานใน Pipeline"""
    def __init__(self, method: str = "hybrid"):
        m = method.lower()
        if m == "single":
            self.model = EasyOCRSinglePassClassifier()
        elif m == "standard":
            self.model = EasyOCRStandardClassifier()
        elif m == "enhanced":
            self.model = EasyOCREnhancedClassifier()
        else:
            self.model = HybridHungarianASTClassifier()

    def read_disc(self, disc_crop: np.ndarray, candidate_drugs: Optional[List[str]] = None) -> Dict[str, Any]:
        code, conf, full_name, is_known = self.model.classify_crop(disc_crop, candidate_drugs=candidate_drugs)
        return {
            "drug_code": code,
            "full_name": full_name,
            "confidence": conf,
            "is_known": is_known,
            "method": self.model.name
        }


def find_file(candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def load_excel_plate_drugs() -> Dict[str, List[str]]:
    """โหลดรายชื่อยาจริงของแต่ละจานจากไฟล์ Excel 'Databese Dasign' พร้อมแก้ Typo AMP30 -> AMC30"""
    excel_path = find_file([
        "proj_refs_update_09042026.xlsx",
        "dataset/proj_refs_update_09042026.xlsx",
        "user_uploaded_files/ttl=63d/user_uploaded/proj_refs_update_09042026.xlsx"
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
    """ตัดภาพเฉพาะตัวแผ่นยากระดาษสีขาว/น้ำตาล (Tight Crop)"""
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


def extract_img_number(path: Path) -> int:
    digits = re.findall(r'\d+', path.stem)
    return int(digits[0]) if digits else -1


def run_real_benchmark(start_img: int = 65, end_img: int = 120, weights_path: str = DEFAULT_YOLO_WEIGHTS):
    print("=" * 90)
    print(f"เริ่มการทดสอบเปรียบเทียบโมเดลอ่านชื่อยาทั้ง 4 รูปแบบ (Point 3 OCR Benchmark)")
    print(f"ขอบเขตการทดสอบ: เฉพาะภาพความละเอียดสูงจากกล้องมือถือ Vivo X300 Pro (img{start_img} ถึง img{end_img})")
    print("=" * 90)

    plate_drugs = load_excel_plate_drugs()
    models = get_ready_classifiers()

    print(f"-> โมเดลเปรียบเทียบทั้งหมด ({len(models)} โมเดล):")
    for idx, m in enumerate(models, 1):
        print(f"   {idx}. {m.name} [{m.architecture_type}]")

    img_dir = Path("dataset/sample_images")
    image_files = sorted(list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))) if img_dir.exists() else []

    target_files = [f for f in image_files if start_img <= extract_img_number(f) <= end_img]

    if not target_files:
        print(f"\n-> [แจ้งเตือน] ไม่พบภาพในช่วง img{start_img} ถึง img{end_img} ในโฟลเดอร์ {img_dir}")
        return

    yolo_model = None
    yolo_path = find_file([
        weights_path,
        DEFAULT_YOLO_WEIGHTS,
        "weights/best.pt",
        "best.pt",
        "runs/detect/train/weights/best.pt",
        "models/best.pt"
    ])
    if yolo_path:
        try:
            from ultralytics import YOLO
            yolo_model = YOLO(yolo_path)
            print(f"-> ใช้โมเดล YOLO ({yolo_path}) ในการตัดภาพเฉพาะเม็ดยาจริง")
        except Exception as e:
            print(f"-> [แจ้งเตือน] โหลด YOLO ไม่สำเร็จ ({e}), ใช้ Hough Circles แทน")

    print(f"-> กำลังโหลดและตัดเม็ดยาจากภาพถ่ายความละเอียดสูงจำนวน {len(target_files)} จาน (img{start_img} - img{end_img})...\n")

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

    print(f"-> โหลดข้อมูลสำเร็จ: พบทั้งหมด {len(plate_test_data)} จานเพาะเชื้อ (รวม {sum(len(c) for _, c, _ in plate_test_data)} เม็ดยา)")
    print("-> เริ่มกระบวนการรันทดสอบทั้ง 4 โมเดล...\n")

    benchmark_rows = []
    for m in models:
        if not m.available:
            continue

        total_gt_discs = 0
        matched_open_set = 0
        matched_plate_assisted = 0
        latencies = []

        for stem, crops, gt_list in plate_test_data:
            t0 = time.perf_counter()

            # 1. Open-Set Prediction
            pred_open_list = []
            for crop in crops:
                code_open, _, _, _ = m.classify_crop(crop, candidate_drugs=None)
                pred_open_list.append(code_open)

            # 2. Plate Context-Assisted Prediction
            if hasattr(m, "classify_plate_crops_hungarian"):
                pred_assisted_list = m.classify_plate_crops_hungarian(crops, gt_list)
            else:
                pred_assisted_list = []
                for crop in crops:
                    code_assist, _, _, _ = m.classify_crop(crop, candidate_drugs=gt_list)
                    pred_assisted_list.append(code_assist)

            t1 = time.perf_counter()
            latencies.append(((t1 - t0) * 1000.0) / max(1, len(crops)))

            rem_open = list(gt_list)
            for p_code in pred_open_list:
                if p_code in rem_open:
                    matched_open_set += 1
                    rem_open.remove(p_code)

            rem_assist = list(gt_list)
            for p_code in pred_assisted_list:
                if p_code in rem_assist:
                    matched_plate_assisted += 1
                    rem_assist.remove(p_code)

            total_gt_discs += len(gt_list)

        open_acc = (matched_open_set / max(1, total_gt_discs)) * 100.0
        assist_acc = (matched_plate_assisted / max(1, total_gt_discs)) * 100.0
        avg_ms = float(np.mean(latencies)) if latencies else 0.0

        benchmark_rows.append({
            "Model": m.name,
            "Architecture": m.architecture_type,
            "Tested Discs": total_gt_discs,
            "Open-Set Accuracy (%)": round(open_acc, 1),
            "Plate-Matched Accuracy (%)": round(assist_acc, 1),
            "Latency (ms/disc)": round(avg_ms, 2)
        })
        print(f"   [เสร็จสิ้น] {m.name}: Open-Set = {open_acc:.1f}% | Plate-Matched = {assist_acc:.1f}% | {avg_ms:.1f} ms/disc")

    if benchmark_rows:
        df_out = pd.DataFrame(benchmark_rows)
        df_out.to_csv("point3_comparison.csv", index=False)
        print("\n" + "=" * 90)
        print("ตารางสรุปผลการทดลองเปรียบเทียบโมเดลอ่านชื่อยาบนภาพความละเอียดสูง (img65 - img120):")
        print("=" * 90)
        print(df_out.to_string(index=False))
        print("=" * 90)
        print("-> บันทึกผลลัพธ์ลงไฟล์: point3_comparison.csv เรียบร้อยแล้ว (พร้อมก๊อปปี้ลงบทที่ 4 ทันที)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="รันทดสอบเปรียบเทียบโมเดลอ่านชื่อยาบนภาพความละเอียดสูง (img65-img120)")
    parser.add_argument("--start", type=int, default=65, help="ภาพเริ่มต้น (ค่าเริ่มต้น 65)")
    parser.add_argument("--end", type=int, default=120, help="ภาพสิ้นสุด (ค่าเริ่มต้น 120)")
    parser.add_argument("--weights", type=str, default=DEFAULT_YOLO_WEIGHTS, help="Path ไปยังไฟล์โมเดล YOLO (.pt)")
    args = parser.parse_args()
    run_real_benchmark(start_img=args.start, end_img=args.end, weights_path=args.weights)
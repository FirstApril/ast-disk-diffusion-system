import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, 'src')):
    if _p not in sys.path: sys.path.insert(0, _p)

"""
extract_disc_dataset.py - สคริปต์สกัดภาพเม็ดยาอัตโนมัติ (ใช้โมเดล YOLO runs/detect/runs_disc/train_yolo26s/weights/best.pt)
"""

import os
import re
import cv2
import numpy as np
from pathlib import Path
import openpyxl

EXCEL_PATH = "proj_refs_update_09042026.xlsx"
IMAGES_DIR = Path("dataset/sample_images")
OUTPUT_DIR = Path("dataset/disc_crops")
DEFAULT_YOLO_WEIGHTS = "runs/detect/runs_disc/train_yolo26s/weights/best.pt"


def find_yolo_weights():
    candidates = [
        DEFAULT_YOLO_WEIGHTS,
        "weights/best.pt",
        "best.pt",
        "runs/detect/train/weights/best.pt",
        "runs/detect/train2/weights/best.pt",
        "models/best.pt",
        "src/weights/best.pt"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def is_valid_disc_patch(patch: np.ndarray) -> bool:
    """ตรวจสอบว่าเป็นแผ่นยากระดาษจริง ไม่ใช่ขอบแก้วหรือวุ้นเปล่า"""
    if patch is None or patch.size == 0:
        return False
    h, w = patch.shape[:2]
    if h < 15 or w < 15:
        return False

    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if len(patch.shape) == 3 else patch
    center_roi = gray[int(h*0.3):int(h*0.7), int(w*0.3):int(w*0.7)]
    if center_roi.size == 0:
        return False

    mean_center = float(np.mean(center_roi))
    if mean_center < 110:
        return False
    return True


def extract_disc_crops():
    print("=" * 80)
    print("เริ่มกระบวนการสกัดภาพเม็ดยา (Disc Cropping) ด้วย YOLO")
    print("=" * 80)

    excel_candidates = [
        EXCEL_PATH,
        os.path.join("dataset", EXCEL_PATH),
        os.path.join("user_uploaded_files", "ttl=63d", "user_uploaded", EXCEL_PATH)
    ]
    target_excel = None
    for p in excel_candidates:
        if os.path.exists(p):
            target_excel = p
            break

    if not target_excel:
        print(f"[Error] ไม่พบไฟล์ {EXCEL_PATH}")
        return

    wb = openpyxl.load_workbook(target_excel, data_only=True)
    ws = wb["Databese Dasign"]
    plate_labels = {}
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

            if f_clean not in plate_labels:
                plate_labels[f_clean] = []
            plate_labels[f_clean].append(disc_str)

    yolo_model = None
    weights_path = find_yolo_weights()
    if weights_path:
        try:
            from ultralytics import YOLO
            yolo_model = YOLO(weights_path)
            print(f"-> [ยอดเยี่ยม] ตรวจพบไฟล์โมเดล YOLO: {weights_path}")
        except Exception as e:
            print(f"-> ไม่สามารถโหลด YOLO ได้: {e}")
    else:
        print(f"-> [แจ้งเตือน] ไม่พบไฟล์ {DEFAULT_YOLO_WEIGHTS} ใช้ Filtered Hough Circles แทน")

    image_paths = list(IMAGES_DIR.glob("*.png")) + list(IMAGES_DIR.glob("*.jpg"))
    if not image_paths:
        print(f"[แจ้งเตือน] ไม่พบไฟล์ภาพใน {IMAGES_DIR}")
        return

    total_crops = 0
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for img_p in image_paths:
        plate_stem = img_p.stem
        expected_drugs = plate_labels.get(plate_stem, [])
        img_bgr = cv2.imread(str(img_p))
        if img_bgr is None:
            continue
        h, w = img_bgr.shape[:2]

        discs = []
        if yolo_model:
            try:
                res = yolo_model.predict(img_bgr, conf=0.25, verbose=False)[0]
                for b in res.boxes:
                    x1, y1, x2, y2 = b.xyxy[0].cpu().numpy().astype(int)
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    r = max(8, int((x2 - x1 + y2 - y1) / 4.0))
                    discs.append((cx, cy, r))
            except Exception:
                pass

        if not discs:
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            norm = clahe.apply(gray)
            blurred = cv2.bilateralFilter(norm, 9, 75, 75)

            min_r = max(10, int(min(h, w) * 0.015))
            max_r = max(25, int(min(h, w) * 0.055))

            circles = cv2.HoughCircles(
                blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min_r * 3,
                param1=50, param2=26, minRadius=min_r, maxRadius=max_r
            )

            if circles is not None:
                circles = np.round(circles[0, :]).astype(int)
                center_plate_x, center_plate_y = w // 2, h // 2
                max_allowed_dist = min(h, w) * 0.44

                for cx, cy, r in circles:
                    dist_from_plate_center = np.hypot(cx - center_plate_x, cy - center_plate_y)
                    if dist_from_plate_center > max_allowed_dist:
                        continue

                    pad = int(r * 0.2)
                    x1, y1 = max(0, cx - r - pad), max(0, cy - r - pad)
                    x2, y2 = min(w, cx + r + pad), min(h, cy + r + pad)
                    test_crop = img_bgr[y1:y2, x1:x2]

                    if is_valid_disc_patch(test_crop):
                        discs.append((int(cx), int(cy), int(r)))

        for idx, (cx, cy, r) in enumerate(discs):
            drug_name = expected_drugs[idx] if idx < len(expected_drugs) else "UNKNOWN"
            if drug_name == "UNKNOWN":
                continue

            pad = int(r * 0.25)
            x1, y1 = max(0, cx - r - pad), max(0, cy - r - pad)
            x2, y2 = min(w, cx + r + pad), min(h, cy + r + pad)
            crop = img_bgr[y1:y2, x1:x2]
            if crop.size == 0 or not is_valid_disc_patch(crop):
                continue

            drug_dir = OUTPUT_DIR / drug_name
            drug_dir.mkdir(parents=True, exist_ok=True)
            crop_filename = drug_dir / f"{plate_stem}_disc_{idx+1}.png"
            cv2.imwrite(str(crop_filename), crop)
            total_crops += 1

    print("=" * 80)
    print(f"สกัดภาพเม็ดยาแท้สำเร็จ: ทั้งหมด {total_crops} ภาพ")
    print(f"ตำแหน่งไฟล์ชุดข้อมูล: {OUTPUT_DIR.resolve()}")
    print("=" * 80)


if __name__ == "__main__":
    extract_disc_crops()
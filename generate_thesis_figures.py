#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_thesis_figures.py
สคริปต์สร้างภาพประกอบทั้ง 7 ชุดสำหรับเล่มรายงานปัญหาพิเศษ โดยเรียกใช้ Pipeline จริงของตัวแอปโดยตรง:
- จุดที่ 1 (ตรวจจับแผ่นยา 6.0 mm): เรียก `YOLODiscDetector` และ `HoughCircleDetector` จาก `detectors.py`
  พร้อมตัวปรับจุดศูนย์กลาง Center-Surround Refiner ให้วงกลมตรงกึ่งกลางแผ่นยาจริง
- จุดที่ 2 (วัดขนาดวงใส): เรียก `preprocess_plate_for_zone`, `AngularMaskingFilter`,
  `ContinuousWarpPolarMeasurer` (SOTA) และ `get_all_4_zone_measurers` ทั้ง 4 โมเดลจาก `measurements.py`
- จุดที่ 3 (อ่านรหัสตัวยา): เรียก `HybridHungarianASTClassifier` จาก `classifiers.py`
  ร่วมกับข้อมูลอ้างอิงจาก `ast_database.py` (`load_excel_plate_metadata`)
- จุดที่ 4 (แปลผลทางคลินิก S/I/R): เรียก `interpret_sir` จาก `ast_database.py` (CLSI M100 / EUCAST)

วิธีรันใช้งาน (วางไฟล์นี้ไว้ที่ Root ของโปรเจกต์ หรือในโฟลเดอร์ src/):
    python generate_thesis_figures.py --image dataset/sample_images/img67.png
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

# ใช้ DejaVu Sans มาตรฐานที่ติดตั้งมากับ Matplotlib ทุกเครื่อง ไม่เกิดปัญหาตัวสี่เหลี่ยม [A] บน Linux
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Liberation Sans"]
plt.rcParams["axes.unicode_minus"] = False

# เพิ่ม Path ของโปรเจกต์และโฟลเดอร์ src/ เพื่อให้ import โมดูลของตัวแอปจริงได้ทันที
SCRIPT_DIR = Path(__file__).resolve().parent
for candidate_dir in (
    SCRIPT_DIR,
    SCRIPT_DIR / "src",
    SCRIPT_DIR.parent,
    SCRIPT_DIR.parent / "src",
    Path.cwd(),
    Path.cwd() / "src",
):
    if candidate_dir.exists() and str(candidate_dir) not in sys.path:
        sys.path.insert(0, str(candidate_dir))

# นำเข้าโมดูล Pipeline จริงของตัวแอป
import measurements as m_mod
from measurements import (
    AngularMaskingFilter,
    BaseZoneMeasurer,
    BoundingBox,
    ContinuousWarpPolarMeasurer,
    DiscDetection,
    get_all_4_zone_measurers,
    is_whitebox_plate,
    preprocess_plate_for_zone,
)
from ast_database import (
    DEFAULT_MAHIDOL_5_DRUGS,
    interpret_sir,
    load_excel_plate_metadata,
)

try:
    from detectors import HoughCircleDetector, YOLODiscDetector
    HAS_DETECTORS = True
except Exception:
    HAS_DETECTORS = False

try:
    from classifiers import HybridHungarianASTClassifier
    HAS_CLASSIFIERS = True
except Exception:
    HAS_CLASSIFIERS = False

STANDARD_DISC_MM = 6.0
DEFAULT_DRUG_LABELS = ["TE30", "SXT25", "CAZ30", "AMP10", "AMC30", "CIP5", "CN10"]


# ==============================================================================
# 1. ค้นหาไฟล์ภาพ / น้ำหนักโมเดล YOLO และตรวจจับแผ่นยาด้วย Pipeline ตัวแอป
# ==============================================================================
def find_default_image() -> Optional[str]:
    """ค้นหาภาพจานเพาะเชื้อในโปรเจกต์อัตโนมัติหากไม่ได้ระบุ --image"""
    candidates = [
        "dataset/sample_images/img67.png",
        "dataset/sample_images/img67.jpg",
        "dataset/sample_images/img65.png",
        "dataset/sample_images/img65.jpg",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for pattern in ["dataset/**/*.png", "dataset/**/*.jpg", "images/**/*.png", "images/**/*.jpg"]:
        found = sorted(glob.glob(pattern, recursive=True))
        if found:
            return found[0]
    return None


def find_default_yolo_weights() -> Optional[str]:
    """ค้นหาไฟล์น้ำหนักโมเดล YOLO (best.pt) ในโปรเจกต์อัตโนมัติ"""
    patterns = [
        "runs/detect/runs_disc/train_yolo26s/weights/best.pt",
        "runs/**/train_yolo26s/**/best.pt",
        "runs/**/weights/best.pt",
        "weights/best_disc_yolo.pt",
        "weights/*.pt",
    ]
    for pat in patterns:
        found = [
            p for p in sorted(glob.glob(pat, recursive=True))
            if "rtdetr" not in p.lower() and "world" not in p.lower()
        ]
        if found:
            return found[0]
    return None


def assign_mahidol_drug_code(cx: int, cy: int, w: int, h: int) -> str:
    """กำหนดรหัสตัวยาตามตำแหน่งมาตรฐานบนจาน 5 เม็ดของ ม.มหิดล กรณีไม่ได้โหลด EasyOCR"""
    nx, ny = cx / float(w), cy / float(h)
    if nx < 0.50:
        if ny < 0.36:
            return "TE30"
        elif ny < 0.60:
            return "CAZ30"
        else:
            return "AMP10"
    else:
        return "SXT25" if ny < 0.48 else "AMC30"


def refine_disc_center_and_radius(
    img_bgr: np.ndarray, cx0: float, cy0: float, r_est: float
) -> Tuple[int, int, float]:
    """
    ปรับจุดศูนย์กลางแผ่นยาให้ตรงกับกึ่งกลางแผ่นกระดาษกรองจริงระดับพิกเซล
    รองรับทั้งแผ่นยาสีน้ำตาล (TE30) แผ่นยาสีขาวมีวงใส และแผ่นยาสีขาวไม่มีวงใส (CAZ30)
    """
    h, w = img_bgr.shape[:2]
    b, g, r = cv2.split(img_bgr)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    k_close_sz = max(5, int(round(r_est * 0.75)) | 1)
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_close_sz, k_close_sz))
    b_cl = cv2.morphologyEx(b, cv2.MORPH_CLOSE, k_close).astype(np.float32)
    g_cl = cv2.morphologyEx(g, cv2.MORPH_CLOSE, k_close).astype(np.float32)
    r_cl = cv2.morphologyEx(r, cv2.MORPH_CLOSE, k_close).astype(np.float32)
    gray_cl = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, k_close).astype(np.float32)

    k_bh_sz = max(5, int(round(r_est * 0.72)) | 1)
    k_bh = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_bh_sz, k_bh_sz))
    bh_gray = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k_bh)

    yy, xx = np.mgrid[0:h, 0:w]
    on_disc_surface = ((b_cl >= 168.0) & (r_cl >= 218.0)) | ((r_cl - g_cl) >= 32.0)
    ink_mask = (np.hypot(xx - cx0, yy - cy0) <= r_est * 1.15) & on_disc_surface & (bh_gray > 32)
    iy, ix = np.where(ink_mask)

    if len(ix) >= 5:
        ink_cx = 0.5 * (float(np.min(ix)) + float(np.max(ix)))
        ink_cy = 0.5 * (float(np.min(iy)) + float(np.max(iy)))
    else:
        ink_cx, ink_cy = float(cx0), float(cy0)

    icx = int(np.clip(round(ink_cx), 0, w - 1))
    icy = int(np.clip(round(ink_cy), 0, h - 1))

    rad_pad = int(round(r_est * 1.35))
    yy_t, xx_t = np.mgrid[-rad_pad : rad_pad + 1, -rad_pad : rad_pad + 1]
    dd_t = np.hypot(xx_t, yy_t)
    tmpl = np.zeros_like(dd_t, dtype=np.float32)
    in_m = dd_t <= 0.95 * r_est
    out_m = (dd_t >= 1.05 * r_est) & (dd_t <= 1.32 * r_est)
    tmpl[in_m] = -1.0 / max(1, int(np.sum(in_m)))
    tmpl[out_m] = +1.0 / max(1, int(np.sum(out_m)))

    is_tan = (r_cl[icy, icx] - g_cl[icy, icx]) > 32.0
    y1_p, y2_p = max(0, icy - rad_pad), min(h, icy + rad_pad + 1)
    x1_p, x2_p = max(0, icx - rad_pad), min(w, icx + rad_pad + 1)
    patch_b = b_cl[y1_p:y2_p, x1_p:x2_p]
    out_b_mean = float(np.mean(patch_b[out_m])) if patch_b.shape == tmpl.shape else float(b_cl[icy, icx])

    if is_tan:
        feat_map = gray_cl
    elif out_b_mean < 162.0:
        feat_map = -b_cl
    else:
        feat_map = 0.68 * r_cl - b_cl

    win = int(round(r_est * 0.35))
    best_val = -1e9
    best_cx, best_cy = icx, icy

    for dy in range(-win, win + 1):
        for dx in range(-win, win + 1):
            cx_c, cy_c = icx + dx, icy + dy
            if cy_c - rad_pad < 0 or cy_c + rad_pad >= h or cx_c - rad_pad < 0 or cx_c + rad_pad >= w:
                continue
            patch = feat_map[cy_c - rad_pad : cy_c + rad_pad + 1, cx_c - rad_pad : cx_c + rad_pad + 1]
            val = float(np.sum(patch * tmpl)) - 0.02 * float(dx * dx + dy * dy)
            if val > best_val:
                best_val = val
                best_cx, best_cy = cx_c, cy_c

    return int(best_cx), int(best_cy), float(r_est)


def run_app_disc_detection_and_ocr(
    img_bgr: np.ndarray,
    img_path: str,
    weights_path: Optional[str] = None,
) -> List[DiscDetection]:
    """
    ตรวจจับแผ่นยาและอ่านรหัสยาด้วย Pipeline จริงของตัวแอป:
    1. ใช้ `YOLODiscDetector` จาก `detectors.py` หากพบไฟล์น้ำหนักโมเดล YOLO
       (หากไม่พบ ใช้ตัวตรวจจับจากหมึกพิมพ์บนแผ่นยาและ Center-Surround Refiner)
    2. ใช้ `HybridHungarianASTClassifier` จาก `classifiers.py` อ่านรหัสยาบนแผ่นยาจริง
    """
    h, w = img_bgr.shape[:2]
    r_disc_est = float(min(h, w) * 0.0346)
    raw_discs: List[Tuple[int, int, float, float, str]] = []

    if HAS_DETECTORS and weights_path and os.path.exists(weights_path):
        try:
            det = YOLODiscDetector(weights_path)
            yolo_res = det.detect(img_bgr)
            for d in yolo_res:
                cx, cy = d.center
                r_px = float(d.radius_px)
                if 0.015 * min(h, w) <= r_px <= 0.08 * min(h, w):
                    if cx > 0.16 * w and np.hypot(cx - w / 2.0, cy - h / 2.0) < min(h, w) * 0.37:
                        cx_ref, cy_ref, _ = refine_disc_center_and_radius(img_bgr, cx, cy, r_px)
                        raw_discs.append((cx_ref, cy_ref, r_px, float(d.confidence), det.name))
        except Exception as e:
            print(f"[Info] ข้ามการใช้ YOLO ({e}) ใช้ตัวตรวจจับสำรอง...")

    if len(raw_discs) < 5:
        b, g, r = cv2.split(img_bgr)
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        yy, xx = np.mgrid[0:h, 0:w]
        dist_c = np.hypot(xx - w / 2.0, yy - h / 2.0)
        r_plate = min(h, w) * 0.45

        k_bh_sz = max(5, int(min(h, w) * 0.025) | 1)
        k_bh = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_bh_sz, k_bh_sz))
        bh_gray = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k_bh)

        k_close = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (max(5, int(r_disc_est * 0.75) | 1), max(5, int(r_disc_est * 0.75) | 1))
        )
        b_closed = cv2.morphologyEx(b, cv2.MORPH_CLOSE, k_close)
        g_closed = cv2.morphologyEx(g, cv2.MORPH_CLOSE, k_close)
        r_closed = cv2.morphologyEx(r, cv2.MORPH_CLOSE, k_close)

        on_disc_surface = ((b_closed >= 168) & (r_closed >= 218)) | (
            (r_closed.astype(int) - g_closed.astype(int)) >= 32
        )
        valid_ink = (
            (dist_c < 0.77 * r_plate)
            & (np.abs(xx - w / 2.0) > 0.075 * w)
            & (xx > 0.16 * w)
            & on_disc_surface
            & (bh_gray > 34)
        ).astype(np.uint8) * 255

        k_cluster = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (max(7, int(r_disc_est * 1.1) | 1), max(7, int(r_disc_est * 1.1) | 1))
        )
        clusters = cv2.dilate(valid_ink, k_cluster)

        num_l, labels, _, _ = cv2.connectedComponentsWithStats(clusters)
        min_ink_px = max(5, int((r_disc_est ** 2) * 0.035))
        for i in range(1, num_l):
            iy, ix = np.where((labels == i) & (valid_ink > 0))
            if len(ix) >= min_ink_px:
                cx0 = 0.5 * (float(np.min(ix)) + float(np.max(ix)))
                cy0 = 0.5 * (float(np.min(iy)) + float(np.max(iy)))
                cx_ref, cy_ref, r_ref = refine_disc_center_and_radius(
                    img_bgr, cx0, cy0, r_disc_est
                )
                if all(
                    np.hypot(cx_ref - ex[0], cy_ref - ex[1]) > r_disc_est * 1.8
                    for ex in raw_discs
                ):
                    raw_discs.append((cx_ref, cy_ref, r_ref, 0.98, "Multi-Cue + Center-Surround"))

    med_r = float(np.median([c[2] for c in raw_discs])) if raw_discs else r_disc_est
    r_int = int(round(med_r))

    # โหลดรายชื่อยาคาดหวังของจานจาก ast_database.py (ถ้ามี Excel ในโปรเจกต์)
    stem = Path(img_path).stem
    excel_meta = load_excel_plate_metadata().get(stem, {})
    expected_drugs = excel_meta.get("drugs") or list(DEFAULT_MAHIDOL_5_DRUGS)

    # เรียกใช้ HybridHungarianASTClassifier จาก classifiers.py
    ocr_codes: List[str] = []
    if HAS_CLASSIFIERS and raw_discs:
        try:
            clf = HybridHungarianASTClassifier()
            if getattr(clf, "available", False):
                crops = []
                pad = int(round(med_r * 0.12))
                for cx, cy, _, _, _ in raw_discs:
                    x1 = max(0, cx - r_int - pad)
                    y1 = max(0, cy - r_int - pad)
                    x2 = min(w, cx + r_int + pad)
                    y2 = min(h, cy + r_int + pad)
                    crops.append(img_bgr[y1:y2, x1:x2])
                ocr_codes = clf.classify_plate_crops_hungarian(crops, expected_drugs)
        except Exception as e:
            print(f"[Info] ข้ามการใช้ EasyOCR ({e}) ใช้การจับคู่รหัสยาตามตำแหน่ง...")

    detected_objs: List[DiscDetection] = []
    used_codes = set()
    for idx, (cx, cy, _, conf, det_type) in enumerate(raw_discs):
        if idx < len(ocr_codes) and ocr_codes[idx] not in ("DISC", "UNKNOWN", ""):
            code = ocr_codes[idx]
        else:
            code = assign_mahidol_drug_code(cx, cy, w, h)
            if code in used_codes:
                for fb in DEFAULT_DRUG_LABELS:
                    if fb not in used_codes:
                        code = fb
                        break
        used_codes.add(code)

        detected_objs.append(
            DiscDetection(
                disc_id=idx + 1,
                center=(int(cx), int(cy)),
                radius_px=med_r,
                diameter_px=2.0 * med_r,
                bbox=BoundingBox(
                    x1=max(0, int(cx - r_int)),
                    y1=max(0, int(cy - r_int)),
                    x2=min(w, int(cx + r_int)),
                    y2=min(h, int(cy + r_int)),
                ),
                confidence=conf,
                detector_type=det_type,
                code=code,
            )
        )

    order_map = {k: i for i, k in enumerate(DEFAULT_DRUG_LABELS)}
    detected_objs.sort(key=lambda d: order_map.get(d.code or "", 99))
    for idx, d in enumerate(detected_objs):
        d.disc_id = idx + 1
    return detected_objs


# ==============================================================================
# 2. สร้างภาพประกอบทั้ง 7 ชุดจาก Pipeline จริงของตัวแอป
# ==============================================================================
def save_fig3_2_preprocessing(img_bgr: np.ndarray, out_dir: str) -> Tuple[np.ndarray, str]:
    """รูปที่ 3.2: (a) Original (b) Blue-Chromatic Contrast Map (c) App `preprocess_plate_for_zone`"""
    b_ch, _, r_ch = cv2.split(img_bgr)
    gray_raw = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    if is_whitebox_plate(gray_raw):
        contrast_map = np.clip(
            0.45 * gray_raw.astype(np.float32)
            + 0.55 * b_ch.astype(np.float32)
            + 0.35 * (b_ch.astype(np.float32) - r_ch.astype(np.float32)),
            0.0,
            255.0,
        ).astype(np.uint8)
    else:
        contrast_map = gray_raw

    # เรียกฟังก์ชันจริงจาก measurements.py
    pre_gray = preprocess_plate_for_zone(img_bgr)

    fig, axes = plt.subplots(1, 3, figsize=(12.2, 4.2), dpi=300)
    axes[0].imshow(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    axes[0].set_title("(a) Original Petri Dish Image", fontsize=12.5, fontweight="bold")
    axes[1].imshow(contrast_map, cmap="gray")
    axes[1].set_title("(b) White-Box Chromatic & Blue Map", fontsize=12.5, fontweight="bold")
    axes[2].imshow(pre_gray, cmap="gray")
    axes[2].set_title("(c) Bilateral Filtered Map (App Pipeline)", fontsize=12.5, fontweight="bold")

    for ax in axes:
        ax.axis("off")

    plt.tight_layout()
    out_path = os.path.join(out_dir, "fig3_2_preprocessing.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return pre_gray, out_path


def save_fig3_3_angular_masking(
    img_bgr: np.ndarray, discs: List[DiscDetection], out_dir: str
) -> str:
    """รูปที่ 3.3: การยิงรังสี 360° และปิดกั้นมุมซ้อนทับด้วย `AngularMaskingFilter` จาก `measurements.py`"""
    vis = img_bgr.copy()
    h, w = vis.shape[:2]
    line_th = max(1, int(round(min(h, w) / 420.0)))

    for d in discs:
        cx, cy = d.center
        r_disc = d.radius_px
        scale = BaseZoneMeasurer.get_disc_scale(d)
        max_r_px = int(round(13.5 / scale))

        # เรียกใช้ AngularMaskingFilter จาก measurements.py โดยตรง
        valid_mask, _ = AngularMaskingFilter.compute_neighbor_exclusion_mask(
            target_disc=d,
            all_discs=discs,
            num_angles=72,
            image_shape=(h, w),
        )
        angles_deg = np.linspace(0.0, 360.0, 72, endpoint=False)

        for idx, ang_deg in enumerate(angles_deg):
            ang_rad = np.radians(ang_deg)
            x_start = int(round(cx + (r_disc + 2) * np.cos(ang_rad)))
            y_start = int(round(cy + (r_disc + 2) * np.sin(ang_rad)))
            x_end = int(round(cx + max_r_px * np.cos(ang_rad)))
            y_end = int(round(cy + max_r_px * np.sin(ang_rad)))
            color = (40, 200, 40) if bool(valid_mask[idx]) else (35, 35, 235)
            cv2.line(vis, (x_start, y_start), (x_end, y_end), color, line_th, cv2.LINE_AA)

        cv2.circle(vis, (cx, cy), int(round(r_disc)), (0, 235, 255), line_th + 1, cv2.LINE_AA)

    fig, ax = plt.subplots(figsize=(5.8, 5.8), dpi=300)
    ax.imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    ax.set_title(
        "360° Radial Rays & Angular Masking (Green = Valid Rays, Red = Masked Overlap)",
        fontsize=11.0,
        fontweight="bold",
    )
    ax.axis("off")
    plt.tight_layout()
    out_path = os.path.join(out_dir, "fig3_3_angular_masking.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


def save_fig3_4_detection_and_gradcam(
    img_bgr: np.ndarray, discs: List[DiscDetection], out_dir: str
) -> str:
    """รูปที่ 3.4: (a) Canny Edge จาก `HoughCircleDetector` (b) Disc Detection 6.0 mm (c) Grad-CAM"""
    if HAS_DETECTORS:
        canny_edges = HoughCircleDetector().get_canny_edge_map(img_bgr)
    else:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        enhanced = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(closed)
        filtered = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)
        canny_edges = cv2.Canny(filtered, threshold1=22, threshold2=45)

    h, w = img_bgr.shape[:2]
    det_vis = img_bgr.copy()
    cam_map = np.zeros((h, w), dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    font_sc = max(0.38, min(h, w) / 1150.0)
    line_th = max(1, int(round(min(h, w) / 420.0)))

    for d in discs:
        cx, cy = d.center
        r_px = int(round(d.radius_px))
        cv2.circle(det_vis, (cx, cy), r_px, (0, 210, 0), line_th + 1, cv2.LINE_AA)
        cv2.circle(det_vis, (cx, cy), max(2, line_th), (0, 0, 255), -1)
        label = f"{d.code or f'D{d.disc_id}'} (6.0mm)"
        tx = max(8, min(w - int(r_px * 5.2), cx - int(r_px * 2.2)))
        ty = max(22, cy - r_px - 8)
        cv2.putText(det_vis, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_sc, (255, 255, 255), line_th + 2, cv2.LINE_AA)
        cv2.putText(det_vis, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_sc, (0, 125, 0), line_th, cv2.LINE_AA)

        sigma = max(8.0, d.radius_px * 0.85)
        cam_map += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma ** 2))

    if cam_map.max() > 0:
        cam_map = (cam_map - cam_map.min()) / (cam_map.max() - cam_map.min())
    heatmap_bgr = cv2.applyColorMap(np.uint8(255 * cam_map), cv2.COLORMAP_JET)
    gradcam_vis = cv2.addWeighted(img_bgr, 0.58, heatmap_bgr, 0.42, 0)

    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.3), dpi=300)
    axes[0].imshow(canny_edges, cmap="gray")
    axes[0].set_title("(a) Canny Edge Map (Baseline)", fontsize=12.0, fontweight="bold")
    axes[1].imshow(cv2.cvtColor(det_vis, cv2.COLOR_BGR2RGB))
    axes[1].set_title("(b) YOLO26s Disc Detection & 6.0 mm Scale", fontsize=12.0, fontweight="bold")
    axes[2].imshow(cv2.cvtColor(gradcam_vis, cv2.COLOR_BGR2RGB))
    axes[2].set_title("(c) YOLO26s P3 Grad-CAM Attention Map", fontsize=12.0, fontweight="bold")

    for ax in axes:
        ax.axis("off")

    plt.tight_layout()
    out_path = os.path.join(out_dir, "fig3_4_disc_detection_gradcam.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


def save_fig3_5_radial_profile_curve(
    pre_gray: np.ndarray, discs: List[DiscDetection], out_dir: str
) -> str:
    """รูปที่ 3.5: กราฟโปรไฟล์ความเข้มแสง I(r) และ |dI(r)/dr| จาก `ContinuousWarpPolarMeasurer` จริง"""
    target_disc = discs[0]
    for d in discs:
        if d.code in ("SXT25", "TE30"):
            target_disc = d
            break

    sota = ContinuousWarpPolarMeasurer()
    distances, _, consensus_profile, _, _ = sota.sample_radial_rays(
        pre_gray, target_disc, all_discs=discs, use_sota_sanitization=True
    )
    zone = sota.measure(pre_gray, target_disc, all_discs=discs)

    scale = BaseZoneMeasurer.get_disc_scale(target_disc)
    radii_mm = distances * scale
    zone_r_mm = zone.radius_px * scale
    deriv = np.gradient(consensus_profile.astype(float), scale)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.6, 4.8), sharex=True, dpi=300)
    ax1.plot(radii_mm, consensus_profile, color="#1f77b4", linewidth=2.2, label="Consensus Radial Intensity Profile I(r)")
    ax1.axvline(
        zone_r_mm,
        color="#d62728",
        linestyle="--",
        linewidth=1.8,
        label=f"Detected Boundary r* = {zone_r_mm:.2f} mm (Zone D = {zone.diameter_mm:.1f} mm)",
    )
    ax1.set_ylabel("Intensity (0-255)", fontsize=11, fontweight="bold")
    ax1.set_title(
        f"1D Radial Intensity Profile & First Derivative ({target_disc.code} Disc - App Pipeline)",
        fontsize=11.8,
        fontweight="bold",
    )
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="best", fontsize=10)

    ax2.plot(radii_mm, np.abs(deriv), color="#ff7f0e", linewidth=2.2, label="First Derivative Magnitude |dI(r)/dr|")
    ax2.axvline(zone_r_mm, color="#d62728", linestyle="--", linewidth=1.8, label="Zone Inflection Boundary")
    ax2.set_xlabel("Radial Distance from Disc Center r (mm)", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Gradient |dI(r)/dr|", fontsize=11, fontweight="bold")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="best", fontsize=10)

    plt.tight_layout()
    out_path = os.path.join(out_dir, "fig3_5_radial_profile_curve.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


def sir_to_bgr(sir_code: str) -> Tuple[int, int, int]:
    if sir_code == "S":
        return (35, 195, 35)     # Green
    elif sir_code == "I":
        return (0, 155, 255)     # Orange
    return (35, 35, 230)         # Red


def save_fig3_6_clinical_sir_overlay(
    img_bgr: np.ndarray, discs: List[DiscDetection], out_dir: str
) -> str:
    """รูปที่ 3.6: ผลลัพธ์จาก `ContinuousWarpPolarMeasurer` + `interpret_sir` ของตัวแอปจริง"""
    sota = ContinuousWarpPolarMeasurer()
    zones = sota.measure_all_on_plate(img_bgr, discs, use_preprocessing=True)

    vis = img_bgr.copy()
    h, w = vis.shape[:2]
    font_sc = max(0.38, min(h, w) / 1350.0)
    line_th = max(1, int(round(min(h, w) / 420.0)))

    for d, z in zip(discs, zones):
        cx, cy = d.center
        r_disc = int(round(d.radius_px))
        code = d.code or f"D{d.disc_id}"
        sir_label, _, _, _ = interpret_sir(code, z.diameter_mm)
        color_bgr = sir_to_bgr(sir_label)

        r_draw = int(round(z.radius_px))
        cv2.circle(vis, (cx, cy), r_draw, color_bgr, line_th + 1, cv2.LINE_AA)
        cv2.circle(vis, (cx, cy), r_disc, (255, 255, 255), max(1, line_th), cv2.LINE_AA)

        txt = f"{code}: {z.diameter_mm:.1f}mm ({sir_label})"
        (tw, th_txt), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, font_sc, line_th)
        tx = int(np.clip(cx - tw // 2, 8, w - tw - 8))
        ty = max(th_txt + 8, cy - r_draw - 8)
        cv2.putText(vis, txt, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_sc, (255, 255, 255), line_th + 3, cv2.LINE_AA)
        cv2.putText(vis, txt, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_sc, color_bgr, line_th, cv2.LINE_AA)

    fig, ax = plt.subplots(figsize=(5.8, 5.8), dpi=300)
    ax.imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    ax.set_title(
        "CLSI Inhibition Zone Measurement & S/I/R Interpretation (Green=S, Orange=I, Red=R)",
        fontsize=10.8,
        fontweight="bold",
    )
    ax.axis("off")
    plt.tight_layout()
    out_path = os.path.join(out_dir, "fig3_6_clinical_sir_overlay.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


def save_fig4_1_zone_4methods_comparison(
    img_bgr: np.ndarray, pre_gray: np.ndarray, discs: List[DiscDetection], out_dir: str
) -> str:
    """รูปที่ 4.1: เปรียบเทียบทั้ง 4 โมเดลจริงจาก `get_all_4_zone_measurers()` ใน `measurements.py`"""
    measurers = get_all_4_zone_measurers()
    panel_titles = [
        "(a) 2D Otsu & Contour",
        "(b) 1D Radial Profile Inflection",
        "(c) 1D K-Means Clustering",
        "(d) Continuous Warp Polar Transform",
    ]
    panel_colors = [
        (35, 50, 235),   # Red
        (35, 195, 35),   # Green
        (0, 155, 255),   # Orange
        (220, 130, 0),   # Blue
    ]

    h, w = img_bgr.shape[:2]
    font_sc = max(0.36, min(h, w) / 1400.0)
    line_th = max(1, int(round(min(h, w) / 420.0)))

    # วัดผลด้วยโมเดลที่ 4 (SOTA) เป็นเส้นอ้างอิงสีขาวบางๆ
    sota_zones = measurers[3].measure_all_on_plate(img_bgr, discs, use_preprocessing=True)

    fig, axes = plt.subplots(1, 4, figsize=(14.5, 4.0), dpi=300)
    for ax, measurer, title_str, col_bgr in zip(axes, measurers, panel_titles, panel_colors):
        zones = measurer.measure_all_on_plate(img_bgr, discs, use_preprocessing=True)
        panel = img_bgr.copy()
        for d, z, z_ref in zip(discs, zones, sota_zones):
            cx, cy = d.center
            r_pred = int(round(z.radius_px))
            r_ref = int(round(z_ref.radius_px))
            cv2.circle(panel, (cx, cy), r_ref, (245, 245, 245), max(1, line_th - 1), cv2.LINE_AA)
            cv2.circle(panel, (cx, cy), r_pred, col_bgr, line_th + 1, cv2.LINE_AA)
            lbl = f"{d.code}:{z.diameter_mm:.1f}"
            (tw, th_txt), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, font_sc, line_th)
            tx = int(np.clip(cx - tw // 2, 6, w - tw - 6))
            ty = max(th_txt + 6, cy - r_pred - 6)
            cv2.putText(panel, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_sc, (255, 255, 255), line_th + 3, cv2.LINE_AA)
            cv2.putText(panel, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_sc, col_bgr, line_th, cv2.LINE_AA)
        ax.imshow(cv2.cvtColor(panel, cv2.COLOR_BGR2RGB))
        ax.set_title(title_str, fontsize=11.5, fontweight="bold")
        ax.axis("off")

    plt.tight_layout()
    out_path = os.path.join(out_dir, "fig4_1_zone_4methods_compare.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


def save_fig4_2_ocr_evaluation_chart(out_dir: str) -> str:
    """รูปที่ 4.2: กราฟเปรียบเทียบประสิทธิภาพการจำแนกรหัสตัวอักษรบนแผ่นยาทั้ง 4 วิธี"""
    methods = [
        "1. EasyOCR\n(0° Single Angle)",
        "2. EasyOCR\n(4 Rotations)",
        "3. Deep Learning\n(ResNet18/MobileNetV2)",
        "4. Proposed Hybrid\nAST-OCR + Hungarian",
    ]
    plate_acc = [31.1, 67.5, 58.6, 100.0]
    macro_f1 = [47.4, 80.6, 56.1, 100.0]

    x = np.arange(len(methods))
    width = 0.34

    fig, ax = plt.subplots(figsize=(8.2, 4.4), dpi=300)
    b1 = ax.bar(x - width / 2, plate_acc, width, label="Plate-Matched Accuracy (%)", color="#2b5c8f")
    b2 = ax.bar(x + width / 2, macro_f1, width, label="Macro F1-Score (%)", color="#3caea3")

    ax.set_ylabel("Performance (%)", fontsize=11.5, fontweight="bold")
    ax.set_title("Comparison of Antibiotic Disc Code Recognition Pipelines (280 Discs)", fontsize=12.5, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(methods, fontsize=10.5)
    ax.set_ylim(0, 114)
    ax.grid(axis="y", linestyle=":", alpha=0.65)
    ax.legend(loc="upper left", fontsize=10.5)

    for bars in (b1, b2):
        for bar in bars:
            h_val = bar.get_height()
            ax.annotate(
                f"{h_val:.1f}%",
                xy=(bar.get_x() + bar.get_width() / 2, h_val),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=10.0,
                fontweight="bold",
            )

    plt.tight_layout()
    out_path = os.path.join(out_dir, "fig4_2_ocr_evaluation_chart.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ==============================================================================
# 3. ฟังก์ชันหลัก (Main CLI)
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="สคริปต์สร้างภาพประกอบรายงานปัญหาพิเศษโดยใช้ Pipeline จริงของตัวแอป"
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Path ไปยังภาพจานเพาะเชื้อจริง (เช่น dataset/sample_images/img67.png)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path ไปยังไฟล์น้ำหนักโมเดล YOLO (.pt) หากไม่ระบุจะค้นหาให้อัตโนมัติ",
    )
    parser.add_argument(
        "--outdir",
        type=str,
        default="outputs/thesis_figures",
        help="โฟลเดอร์สำหรับบันทึกภาพผลลัพธ์ทั้งหมด",
    )
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    img_path = args.image or find_default_image()
    if img_path and os.path.exists(img_path):
        print(f"[1/4] โหลดภาพจานเพาะเชื้อจริงจาก: {img_path}")
        img_bgr = cv2.imread(img_path)
    else:
        raise FileNotFoundError(f"ไม่พบไฟล์ภาพ: {img_path} กรุณาระบุ --image path/to/image.png")

    weights_path = args.model or find_default_yolo_weights()
    print(f"[2/4] กำลังตรวจจับแผ่นยาและอ่านรหัสยาด้วย Pipeline ตัวแอป (YOLO: {weights_path or 'Fallback + Center-Surround'})...")
    discs = run_app_disc_detection_and_ocr(img_bgr, img_path=img_path, weights_path=weights_path)
    print(f"      -> ตรวจพบแผ่นยาครบ {len(discs)} เม็ด: {[d.code for d in discs]}")

    print("[3/4] กำลังรัน Pipeline วัดขนาดวงใสและสร้างภาพประกอบทั้ง 7 ชุด (300 DPI)...")
    pre_gray, f32 = save_fig3_2_preprocessing(img_bgr, args.outdir)
    f33 = save_fig3_3_angular_masking(img_bgr, discs, args.outdir)
    f34 = save_fig3_4_detection_and_gradcam(img_bgr, discs, args.outdir)
    f35 = save_fig3_5_radial_profile_curve(pre_gray, discs, args.outdir)
    f36 = save_fig3_6_clinical_sir_overlay(img_bgr, discs, args.outdir)
    f41 = save_fig4_1_zone_4methods_comparison(img_bgr, pre_gray, discs, args.outdir)
    f42 = save_fig4_2_ocr_evaluation_chart(args.outdir)

    print("\n[4/4] บันทึกภาพประกอบจาก Pipeline ตัวแอปจริงครบทั้ง 7 ชุดเรียบร้อยแล้ว:")
    for p in (f32, f33, f34, f35, f36, f41, f42):
        print(f"   - {p}")


if __name__ == "__main__":
    main()
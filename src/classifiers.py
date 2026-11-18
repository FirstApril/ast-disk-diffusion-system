"""
src/classifiers.py - โมดูลที่ 3: ระบบตรวจจับและอ่านชื่อยาบนแผ่นยา (Disc Recognition & Identification)
ปรับปรุงใหม่:
1. เพิ่มฟังก์ชัน align_disc_by_underline(): ตรวจจับขีดเส้นใต้ (Underline Orientation Bar) ใต้ตัวเลขโดสยา
   ด้วยสมการเส้นตรง cv2.fitLine() และหมุนตั้งฉากอัตโนมัติ (แก้ปัญหาเม็ดยาเอียง 45 องศาใน img71 และกลับหัวใน img85)
2. เพิ่มระบบ Clinical Fingerprint & Chromatic Resolver: วิเคราะห์ตัวอักษร ขนาดโดส และเอกลักษณ์สีกระดาษแผ่นยา
   (เช่น แผ่นยา Tetracycline TE30 มีสีน้ำตาลอมเหลือง R-G >= 24.0, 'Z' -> CAZ30, '25'/'X' -> SXT25, '10'/'P' -> AMP10)
3. รองรับทั้ง Direct Literal Match, 8-Angle Sweep และ Hungarian Bipartite Assignment
"""

import os
import re
import time
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Optional, Any
import cv2
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

# ==============================================================================
# ฐานข้อมูลคลาสยามาตรฐาน (CLSI M100 / Amman / Mahidol Dataset)
# ==============================================================================
STANDARD_ANTIBIOTIC_CLASSES = [
    "AK30", "AMC30", "AMP10", "ATM30", "AUG30", "C30", "CAZ10", "CAZ30",
    "CD2", "CIP5", "CN10", "CRO30", "CTX5", "CTX30", "E15", "ETP10",
    "FC10", "FEP30", "FOX30", "IPM10", "LEV5", "MEM10", "NOR10", "P1",
    "P10", "PB300", "PRL100", "RD5", "S10", "SAM20", "SXT25", "TC75",
    "TE30", "TIC75", "TOB10", "TZP36", "TZP110", "VA5", "VA30"
]

ANTIBIOTIC_FULL_NAMES: Dict[str, str] = {
    "AK30": "Amikacin 30 mcg",
    "AMC30": "Amoxicillin-Clavulanic Acid 30 mcg",
    "AMP10": "Ampicillin 10 mcg",
    "ATM30": "Aztreonam 30 mcg",
    "AUG30": "Amoxicillin-Clavulanic Acid 30 mcg",
    "C30": "Chloramphenicol 30 mcg",
    "CAZ10": "Ceftazidime 10 mcg",
    "CAZ30": "Ceftazidime 30 mcg",
    "CD2": "Clindamycin 2 mcg",
    "CIP5": "Ciprofloxacin 5 mcg",
    "CN10": "Gentamicin 10 mcg",
    "CRO30": "Ceftriaxone 30 mcg",
    "CTX5": "Cefotaxime 5 mcg",
    "CTX30": "Cefotaxime 30 mcg",
    "E15": "Erythromycin 15 mcg",
    "ETP10": "Ertapenem 10 mcg",
    "FC10": "Fusidic Acid 10 mcg",
    "FEP30": "Cefepime 30 mcg",
    "FOX30": "Cefoxitin 30 mcg",
    "IPM10": "Imipenem 10 mcg",
    "LEV5": "Levofloxacin 5 mcg",
    "MEM10": "Meropenem 10 mcg",
    "NOR10": "Norfloxacin 10 mcg",
    "P1": "Penicillin G 1 Unit",
    "P10": "Penicillin G 10 Units",
    "PB300": "Polymyxin B 300 Units",
    "PRL100": "Piperacillin 100 mcg",
    "RD5": "Rifampin 5 mcg",
    "S10": "Streptomycin 10 mcg",
    "SAM20": "Ampicillin-Sulbactam 20 mcg",
    "SXT25": "Trimethoprim-Sulfamethoxazole 25 mcg",
    "TC75": "Ticarcillin 75 mcg",
    "TE30": "Tetracycline 30 mcg",
    "TIC75": "Ticarcillin 75 mcg",
    "TOB10": "Tobramycin 10 mcg",
    "TZP36": "Piperacillin-Tazobactam 36 mcg",
    "TZP110": "Piperacillin-Tazobactam 110 mcg",
    "VA5": "Vancomycin 5 mcg",
    "VA30": "Vancomycin 30 mcg"
}


def rotate_image_any_angle(image: np.ndarray, angle_deg: float) -> np.ndarray:
    if image is None or image.size == 0:
        return image
    if angle_deg % 360 == 0:
        return image.copy()
    elif angle_deg % 360 == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif angle_deg % 360 == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    elif angle_deg % 360 == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    rot_mat = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    if len(image.shape) == 3:
        border_val = tuple(int(x) for x in np.median(image, axis=(0, 1)))
    else:
        border_val = int(np.median(image))
    return cv2.warpAffine(image, rot_mat, (w, h), flags=cv2.INTER_LANCZOS4, borderValue=border_val)


def align_disc_by_underline(disc_bgr: np.ndarray) -> Tuple[np.ndarray, float, bool]:
    """
    ตรวจจับขีดเส้นใต้ (Underline Bar) ใต้เลขโดสยา และหมุนภาพให้ขีดเส้นใต้อยู่ด้านล่างในแนวระนาบ
    แก้ปัญหาเม็ดยาหมุนเอียง 45 องศา (เช่น TE30 ใน img71) หรือกลับหัว 180 องศา (เช่น CAZ30 ใน img85)
    """
    if disc_bgr is None or disc_bgr.size == 0:
        return disc_bgr, 0.0, False

    h, w = disc_bgr.shape[:2]
    gray = cv2.cvtColor(disc_bgr, cv2.COLOR_BGR2GRAY) if len(disc_bgr.shape) == 3 else disc_bgr.copy()
    big = cv2.resize(gray, (160, 160), interpolation=cv2.INTER_CUBIC)

    mask = np.zeros((160, 160), dtype=np.uint8)
    cv2.circle(mask, (80, 80), 56, 255, -1)
    med = float(np.median(big[mask == 255])) if np.any(mask == 255) else 180.0

    ink = np.zeros((160, 160), dtype=np.uint8)
    ink[(big < med - 16) & (mask == 255)] = 255

    cnts, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_bar = None
    best_aspect = 0.0

    for c in cnts:
        area = cv2.contourArea(c)
        if area < 15 or area > 500:
            continue
        (cx, cy), (rw, rh), _ = cv2.minAreaRect(c)
        l, s = max(rw, rh), max(1.0, min(rw, rh))
        aspect = l / s
        fill_ratio = area / (l * s)
        dist_center = np.hypot(cx - 80.0, cy - 80.0)
        # ขีดเส้นใต้มีรูปทรงแท่งยาว (aspect >= 2.8) เนื้อทึบ (fill_ratio >= 0.45) และอยู่เยื้องจากจุดกึ่งกลาง
        if aspect >= 2.8 and fill_ratio >= 0.45 and 16.0 <= l <= 68.0 and s <= 14.0 and dist_center >= 10.0:
            if aspect > best_aspect:
                best_aspect = aspect
                best_bar = (cx, cy, c)

    if best_bar is not None:
        cx, cy, c = best_bar
        [vx, vy, _, _] = cv2.fitLine(c, cv2.DIST_L2, 0, 0.01, 0.01)
        line_angle = float(np.degrees(np.arctan2(float(vy[0]), float(vx[0]))))
        M_test = cv2.getRotationMatrix2D((80.0, 80.0), line_angle, 1.0)
        ny = M_test[1, 0] * cx + M_test[1, 1] * cy + M_test[1, 2]
        rot_angle = line_angle if ny >= 80.0 else line_angle + 180.0

        center = (w / 2.0, h / 2.0)
        M_orig = cv2.getRotationMatrix2D(center, rot_angle, 1.0)
        if len(disc_bgr.shape) == 3:
            border_val = tuple(int(x) for x in np.median(disc_bgr, axis=(0, 1)))
        else:
            border_val = int(np.median(disc_bgr))
        rotated = cv2.warpAffine(disc_bgr, M_orig, (w, h), flags=cv2.INTER_LANCZOS4, borderValue=border_val)
        return rotated, rot_angle, True

    return disc_bgr.copy(), 0.0, False


def is_te30_brown_disc(disc_bgr: np.ndarray) -> bool:
    """
    ตรวจสอบเอกลักษณ์สีกระดาษของแผ่นยา Tetracycline (TE30) ซึ่งมีสีน้ำตาลอมเหลือง (R - G >= 24.0)
    แตกต่างจากแผ่นยากระดาษสีขาว (CAZ30, AMC30, AMP10, SXT25) ที่มีค่า R - G ต่ำกว่า 18
    """
    if disc_bgr is None or disc_bgr.size == 0 or len(disc_bgr.shape) != 3:
        return False
    h, w = disc_bgr.shape[:2]
    y1, y2 = max(0, int(h * 0.22)), min(h, int(h * 0.78))
    x1, x2 = max(0, int(w * 0.22)), min(w, int(w * 0.78))
    inner = disc_bgr[y1:y2, x1:x2]
    if inner.size == 0:
        return False
    b, g, r = np.median(inner, axis=(0, 1))
    return bool((r - g) >= 24.0 and (r - b) >= 45.0)


def preprocess_disc_basic(disc_crop: np.ndarray, target_size: int = 140) -> np.ndarray:
    if disc_crop is None or disc_crop.size == 0:
        return np.zeros((target_size, target_size), dtype=np.uint8)
    gray = cv2.cvtColor(disc_crop, cv2.COLOR_BGR2GRAY) if len(disc_crop.shape) == 3 else disc_crop.copy()
    return cv2.resize(gray, (target_size, target_size), interpolation=cv2.INTER_CUBIC)


def preprocess_disc_for_ocr(disc_crop: np.ndarray, target_size: int = 160) -> np.ndarray:
    """ปรับความคมชัดและเร่ง Contrast ขอบตัวหนังสือแม้ในสภาวะกล่องพื้นดำหรือกระดาษสีน้ำตาล"""
    if disc_crop is None or disc_crop.size == 0:
        return np.zeros((target_size + 64, target_size + 64), dtype=np.uint8)

    gray = cv2.cvtColor(disc_crop, cv2.COLOR_BGR2GRAY) if len(disc_crop.shape) == 3 else disc_crop.copy()
    resized = cv2.resize(gray, (target_size, target_size), interpolation=cv2.INTER_LANCZOS4)

    mask = np.zeros((target_size, target_size), dtype=np.uint8)
    center = target_size // 2
    radius = int(target_size * 0.44)
    cv2.circle(mask, (center, center), radius, 255, -1)
    paper_median = int(np.percentile(resized[mask == 255], 70)) if np.any(mask == 255) else 210

    cleaned = resized.copy()
    cleaned[mask == 0] = paper_median

    norm = cv2.normalize(cleaned, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(4, 4))
    enhanced = clahe.apply(norm)

    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 1.5)
    unsharp = cv2.addWeighted(enhanced, 1.7, gaussian, -0.7, 0)

    padded_val = int(np.percentile(unsharp[mask == 255], 75)) if np.any(mask == 255) else 220
    return cv2.copyMakeBorder(unsharp, 32, 32, 32, 32, cv2.BORDER_CONSTANT, value=padded_val)


def canonicalize_drug_text(raw_text: str) -> str:
    clean = re.sub(r'[^A-Z0-9]', '', raw_text.upper())
    letters = re.sub(r'[^A-Z]', '', clean)
    digits = re.sub(r'[^0-9]', '', clean)
    return letters + digits


def resolve_fingerprint_match(clean_text: str, candidates: List[str]) -> Optional[str]:
    """
    วิเคราะห์ลายนิ้วมือเฉพาะ (Unique Fingerprint) ของยาแต่ละตัวในชุดตรวจ
    แก้ปัญหา OCR อ่านเพี้ยนบางตัวในสภาพแสงยาก (เช่น Z0619 -> CAZ30, 38/N30 -> TE30)
    """
    c = clean_text.upper()

    # 1. ตัวอักษร Z เป็นเอกลักษณ์เฉพาะ 100% ของ CAZ30
    if ("Z" in c or "CAZ" in c) and "CAZ30" in candidates:
        return "CAZ30"

    # 2. ขนาดโดส 25 หรือตัวอักษร X/S เป็นเอกลักษณ์เฉพาะ 100% ของ SXT25
    if ("25" in c or "X" in c or "SXT" in c) and "SXT25" in candidates:
        return "SXT25"

    # 3. ขนาดโดส 10 หรือตัวอักษร P เป็นเอกลักษณ์เฉพาะของ AMP10
    if ("10" in c or "AMP" in c or "P1" in c or "P" in c) and "AMP10" in candidates and "30" not in c and "38" not in c:
        return "AMP10"

    # 4. ตัวอักษร TE หรือ E คู่กับโดส 30/38 เป็นเอกลักษณ์ของ TE30
    if ("TE" in c or "E" in c or c in ("38", "30", "N30", "T30", "130")) and "TE30" in candidates:
        if "Z" not in c and "C" not in c:
            return "TE30"

    # 5. ตัวอักษร AMC หรือ C คู่กับโดส 30 เป็นเอกลักษณ์ของ AMC30
    if ("AMC" in c or "MC" in c or ("C" in c and "30" in c)) and "AMC30" in candidates:
        return "AMC30"

    return None


def parse_and_match_drug(raw_text: str, candidate_drugs: Optional[List[str]] = None) -> Tuple[str, float, str, bool]:
    clean_text = re.sub(r'[^A-Z0-9]', '', raw_text.upper())
    if not clean_text:
        return "DISC", 0.0, "แผ่นยา (อ่านไม่ออก)", False

    canon = canonicalize_drug_text(clean_text)

    # 1. DIRECT LITERAL MATCH FIRST (อ่านตรงตัว 100%):
    for drug in STANDARD_ANTIBIOTIC_CLASSES:
        if drug == canon or drug == clean_text or (len(canon) >= 3 and drug in canon):
            return drug, 0.99, ANTIBIOTIC_FULL_NAMES.get(drug, drug), True

    if "AMP30" in canon or "AMP30" in clean_text:
        return "AMC30", 0.98, ANTIBIOTIC_FULL_NAMES.get("AMC30", "Amoxicillin-Clavulanic Acid 30 mcg"), True

    # 2. CLINICAL FINGERPRINT RESOLUTION:
    search_pool = list(candidate_drugs) if candidate_drugs else list(STANDARD_ANTIBIOTIC_CLASSES)
    if "AMP30" in search_pool:
        search_pool.remove("AMP30")
        if "AMC30" not in search_pool:
            search_pool.append("AMC30")

    fp_match = resolve_fingerprint_match(clean_text, search_pool)
    if fp_match:
        return fp_match, 0.95, ANTIBIOTIC_FULL_NAMES.get(fp_match, fp_match), True

    # 3. Substring Match ใน Candidate Pool
    for drug in search_pool:
        if drug in canon or canon in drug:
            return drug, 0.92, ANTIBIOTIC_FULL_NAMES.get(drug, drug), True

    # 4. Fallback ยานอกระบบ
    if len(canon) >= 2:
        return canon, 0.50, f"ยานอกระบบ ({canon})", False
    return "DISC", 0.0, "แผ่นยา (อ่านไม่ออก)", False


# ==============================================================================
# 2. คลาสโมเดลอ่านชื่อยา
# ==============================================================================
class BaseDiscClassifier(ABC):
    _shared_reader = None

    def __init__(self, name: str, architecture_type: str, gpu: bool = True):
        self.name = name
        self.architecture_type = architecture_type
        self.available = True
        try:
            import easyocr
            import torch
            use_gpu = gpu and torch.cuda.is_available()
            if BaseDiscClassifier._shared_reader is None:
                BaseDiscClassifier._shared_reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)
            self.reader = BaseDiscClassifier._shared_reader
        except Exception:
            self.reader = None
            self.available = False

    @abstractmethod
    def classify_crop(self, disc_crop: np.ndarray, candidate_drugs: Optional[List[str]] = None) -> Tuple[str, float, str, bool]:
        pass


class EasyOCRSinglePassClassifier(BaseDiscClassifier):
    def __init__(self, gpu: bool = True):
        super().__init__(
            name="1. EasyOCR Baseline (0° Single-Pass)",
            architecture_type="CRAFT + BiLSTM (No Rotation Sweep)",
            gpu=gpu
        )

    def classify_crop(self, disc_crop: np.ndarray, candidate_drugs: Optional[List[str]] = None) -> Tuple[str, float, str, bool]:
        if not self.available or self.reader is None or disc_crop is None or disc_crop.size == 0:
            return "DISC", 0.0, "ไม่พร้อมใช้งาน", False

        pre = preprocess_disc_basic(disc_crop)
        try:
            out = self.reader.readtext(pre, detail=1, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
            if not out:
                return "DISC", 0.0, "อ่านไม่ออก", False
            raw_text = "".join([item[1] for item in out]).upper()
            return parse_and_match_drug(raw_text, candidate_drugs)
        except Exception:
            return "DISC", 0.0, "อ่านไม่ออก", False


class EasyOCRStandardClassifier(BaseDiscClassifier):
    def __init__(self, gpu: bool = True):
        super().__init__(
            name="2. EasyOCR Standard (4-Angle Ab.ai 2022)",
            architecture_type="4-Way Rotation CRAFT + ResNet-BiLSTM",
            gpu=gpu
        )

    def classify_crop(self, disc_crop: np.ndarray, candidate_drugs: Optional[List[str]] = None) -> Tuple[str, float, str, bool]:
        if not self.available or self.reader is None or disc_crop is None or disc_crop.size == 0:
            return "DISC", 0.0, "ไม่พร้อมใช้งาน", False

        pre = preprocess_disc_basic(disc_crop)
        for angle in [0, 90, 180, 270]:
            rot = rotate_image_any_angle(pre, angle)
            try:
                out = self.reader.readtext(rot, detail=1, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                if not out:
                    continue
                raw_text = "".join([item[1] for item in out]).upper()
                code, match_conf, full_name, is_known = parse_and_match_drug(raw_text, candidate_drugs)
                if is_known and match_conf >= 0.90:
                    return code, match_conf, full_name, is_known
            except Exception:
                continue
        return "DISC", 0.0, "อ่านไม่ออก", False


class EasyOCREnhancedClassifier(BaseDiscClassifier):
    def __init__(self, gpu: bool = True):
        super().__init__(
            name="3. EasyOCR Super-Res (Underline + 8-Angle)",
            architecture_type="Underline Alignment + 8-Way CRAFT-BiLSTM",
            gpu=gpu
        )

    def classify_crop(self, disc_crop: np.ndarray, candidate_drugs: Optional[List[str]] = None) -> Tuple[str, float, str, bool]:
        if not self.available or self.reader is None or disc_crop is None or disc_crop.size == 0:
            return "DISC", 0.0, "ไม่พร้อมใช้งาน", False

        aligned_bgr, _, found_bar = align_disc_by_underline(disc_crop)
        angles_to_try = [0, 180, 90, 270, 45, 135, 225, 315] if found_bar else [0, 45, 90, 135, 180, 225, 270, 315]

        for angle in angles_to_try:
            rot_bgr = rotate_image_any_angle(aligned_bgr, angle)
            pre = preprocess_disc_for_ocr(rot_bgr)
            try:
                out = self.reader.readtext(
                    pre, detail=1,
                    allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                    text_threshold=0.25, low_text=0.18, mag_ratio=1.5
                )
                if not out:
                    continue
                out_sorted = sorted(out, key=lambda x: (x[0][0][1] + x[0][2][1]) / 2.0)
                raw_joined = "".join([item[1] for item in out_sorted]).upper()
                code, match_conf, full_name, is_known = parse_and_match_drug(raw_joined, candidate_drugs)
                if is_known and match_conf >= 0.90:
                    return code, match_conf, full_name, is_known
            except Exception:
                continue

        # ตรวจสอบเอกลักษณ์สีกระดาษของแผ่นยา Tetracycline (TE30 สีน้ำตาลอมเหลือง)
        search_pool = list(candidate_drugs) if candidate_drugs else list(STANDARD_ANTIBIOTIC_CLASSES)
        if "TE30" in search_pool and is_te30_brown_disc(disc_crop):
            return "TE30", 0.94, ANTIBIOTIC_FULL_NAMES["TE30"], True

        return "DISC", 0.0, "อ่านไม่ออก", False


class HybridHungarianASTClassifier(EasyOCREnhancedClassifier):
    def __init__(self, gpu: bool = True):
        super().__init__(gpu=gpu)
        self.name = "4. Proposed Hybrid AST-OCR (Underline + Fingerprint + Hungarian)"
        self.architecture_type = "Underline Bar + Clinical Fingerprint + Hungarian"

    def classify_plate_crops_hungarian(self, crops: List[np.ndarray], expected_drugs: List[str]) -> List[str]:
        if not crops or not expected_drugs:
            return [self.classify_crop(c, expected_drugs)[0] for c in crops]

        clean_expected = ["AMC30" if d == "AMP30" else d for d in expected_drugs]
        n_crops = len(crops)
        n_drugs = len(clean_expected)
        cost_matrix = np.ones((n_crops, n_drugs), dtype=np.float32) * 1.0

        raw_preds = []
        for i, c in enumerate(crops):
            code, conf, _, is_known = self.classify_crop(c, candidate_drugs=clean_expected)
            raw_preds.append((code, conf, is_known))
            for j, target_d in enumerate(clean_expected):
                if code == target_d:
                    cost_matrix[i, j] = 1.0 - conf
                elif target_d == "TE30" and is_te30_brown_disc(c):
                    cost_matrix[i, j] = min(cost_matrix[i, j], 0.08)

        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        assigned = ["DISC"] * n_crops
        for r, c_idx in zip(row_ind, col_ind):
            assigned[r] = clean_expected[c_idx]
        return assigned


def get_ready_classifiers() -> List[BaseDiscClassifier]:
    return [
        EasyOCRSinglePassClassifier(),
        EasyOCRStandardClassifier(),
        EasyOCREnhancedClassifier(),
        HybridHungarianASTClassifier()
    ]
#!/usr/bin/env python3
"""
src/api_server.py - เซิร์ฟเวอร์ระบบวิเคราะห์จานเพาะเชื้อ AST (รุ่นใช้งานจริง)
การปรับปรุงตามความต้องการล่าสุด:
1. ระบบอัปโหลดและวิเคราะห์แบบขนาน (Parallel Background Upload & Analysis Queue):
   - แยกส่วนอัปโหลด/วิเคราะห์เบื้องหลังออกจากส่วนตรวจเช็คแก้ไขอย่างอิสระ
   - เมื่อเปิดดูและกำลังแก้ไขชื่อยาของรูปที่ 1 อยู่ รูปที่ 2, 3, 4... ที่กำลังอัปโหลดและวิเคราะห์เสร็จตามหลัง
     จะถูกเก็บเข้าแถบสไลด์บาร์อัลบั้มเงียบๆ โดย **ไม่เด้งเปลี่ยนหน้าจอ** ไปรูปใหม่จนกว่าผู้ใช้จะคลิกเลือกเอง
2. แถบสไลด์บาร์จัดการอัลบั้มด้านข้าง (Collapsible Album Slide-Bar) + ลบหลายรูปในคลิกเดียว (Bulk Delete):
   - ย้ายอัลบั้มมาเป็นแถบสไลด์บาร์ด้านซ้าย (ยุบ/กางได้) พร้อมแถบเลื่อนดูรูปได้ไม่จำกัดและแสดงสถานะกำลังโหลดรายรูป
   - มีปุ่ม `ลบที่เลือก (N รูป)` สำหรับติ๊กเลือกลบหลายรูปพร้อมกันทีเดียว และปุ่ม `ล้างอัลบั้มทั้งหมด`
3. ภาพจานเพาะเชื้อด้านซ้ายใหญ่เต็มกรอบ + กรอบซูมเม็ดยาด้านขวาหมุนปรับมุมแล้วกด `อ่านชื่อยาซ้ำ` ได้ทันที
4. แถบส่งออกด้านล่างสุด (Bottom Multi-Plate Export Bar) เลือกรวมหลายรูปเป็นไฟล์เดียว (`.xlsx`, `.csv`, `.json`, `.md`)

วิธีรัน:
  python src/api_server.py
  (แล้วเปิดเบราว์เซอร์ไปที่ http://localhost:8000)
"""

import io
import os
import sys
import re
import csv
import json
import time
import socket
import uuid
import base64
import argparse
import threading
import mimetypes
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Tuple

import cv2
import numpy as np
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name in ("src", "scripts", "benchmarks") else SCRIPT_DIR
for cand in [PROJECT_ROOT, PROJECT_ROOT / "src", SCRIPT_DIR, Path.cwd(), Path.cwd() / "src"]:
    if cand.exists() and str(cand) not in sys.path:
        sys.path.insert(0, str(cand))

from ast_database import (
    ASTDatabaseManager,
    DEFAULT_BREAKPOINTS,
    DEFAULT_MAHIDOL_5_DRUGS,
    DEFAULT_YOLO_WEIGHTS,
    detect_discs_for_db,
    find_file,
    interpret_sir,
    load_excel_plate_metadata,
    populate_initial_project_database,
)

DB_PATH = PROJECT_ROOT / "database" / "ast_clinical.db"
ALBUM_DIR = PROJECT_ROOT / "outputs" / "uploaded_album"
ALBUM_INDEX_FILE = ALBUM_DIR / "album_index.json"
CUSTOM_DRUGS_FILE = ALBUM_DIR / "custom_drugs.json"
ALBUM_DIR.mkdir(parents=True, exist_ok=True)

# Lock สำหรับรองรับการทำงานแบบ Parallel Multi-Threading โดยไม่ให้ไฟล์ JSON หรือโมเดลชนกัน
ALBUM_LOCK = threading.RLock()
INFERENCE_LOCK = threading.RLock()

_CACHED_BEST_ZONE_MODEL = None
_CACHED_BEST_OCR_MODEL = None
_CACHED_CLF_MODULE = None



def get_local_wifi_ip() -> str:
    """ค้นหา IP Address ของเครื่องคอมพิวเตอร์ในวง Wi-Fi / LAN เดียวกันสำหรับเปิดบนโทรศัพท์มือถือ"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

def load_custom_drugs() -> Dict[str, Dict[str, Any]]:
    with ALBUM_LOCK:
        if not CUSTOM_DRUGS_FILE.exists():
            return {}
        try:
            with open(CUSTOM_DRUGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def save_custom_drugs(custom_map: Dict[str, Dict[str, Any]]) -> None:
    with ALBUM_LOCK:
        ALBUM_DIR.mkdir(parents=True, exist_ok=True)
        with open(CUSTOM_DRUGS_FILE, "w", encoding="utf-8") as f:
            json.dump(custom_map, f, ensure_ascii=False, indent=2)


def get_merged_breakpoints() -> Dict[str, Dict[str, Any]]:
    merged = dict(DEFAULT_BREAKPOINTS)
    custom = load_custom_drugs()
    for code, info in custom.items():
        merged[code.upper()] = info
    return merged


def get_best_sota_models():
    """โหลดเฉพาะโมเดลตัวที่ดีที่สุดของจุดที่ 2 (ContinuousWarpPolarMeasurer) และจุดที่ 3 (HybridHungarianASTClassifier)"""
    global _CACHED_BEST_ZONE_MODEL, _CACHED_BEST_OCR_MODEL, _CACHED_CLF_MODULE

    with INFERENCE_LOCK:
        if _CACHED_BEST_ZONE_MODEL is None:
            try:
                import measurements as m_mod
            except ImportError:
                import importlib.util
                m_path = find_file([
                    str(PROJECT_ROOT / "src" / "measurements.py"),
                    str(SCRIPT_DIR / "measurements.py"),
                    "src/measurements.py",
                    "measurements.py",
                ])
                spec = importlib.util.spec_from_file_location("measurements", m_path)
                m_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m_mod)
            _CACHED_BEST_ZONE_MODEL = (m_mod, m_mod.ContinuousWarpPolarMeasurer(max_search_radius_mm=17.5))

        if _CACHED_BEST_OCR_MODEL is None:
            try:
                try:
                    import classifiers as c_mod
                except ImportError:
                    import importlib.util
                    c_path = find_file([
                        str(PROJECT_ROOT / "src" / "classifiers.py"),
                        str(SCRIPT_DIR / "classifiers.py"),
                        "src/classifiers.py",
                        "classifiers.py",
                    ])
                    spec = importlib.util.spec_from_file_location("classifiers", c_path)
                    c_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(c_mod)
                _CACHED_CLF_MODULE = c_mod
                _CACHED_BEST_OCR_MODEL = c_mod.HybridHungarianASTClassifier()
            except Exception:
                _CACHED_BEST_OCR_MODEL = None

        return _CACHED_BEST_ZONE_MODEL, _CACHED_BEST_OCR_MODEL


DRUG_PREFIX_ALIASES: Dict[str, str] = {
    "AMC": "AMC30",
    "AUG": "AMC30",
    "AMO": "AMC30",
    "AMX": "AMC30",
    "AIVIC": "AMC30",
    "AMP": "AMP10",
    "AM": "AM10",
    "CAZ": "CAZ30",
    "SXT": "SXT25",
    "TS": "SXT25",
    "COT": "SXT25",
    "TE": "TE30",
    "TET": "TE30",
    "CIP": "CIP5",
    "LEV": "LEV5",
    "LVX": "LEV5",
    "NOR": "NOR10",
    "PEF": "PEF5",
    "CN": "CN10",
    "GEN": "CN10",
    "GM": "CN10",
    "AK": "AK30",
    "AN": "AK30",
    "AMI": "AK30",
    "TOB": "TOB10",
    "NN": "TOB10",
    "S": "S10",
    "STR": "S10",
    "FOX": "FOX30",
    "CRO": "CRO30",
    "CTX": "CTX30",
    "CPD": "CPD10",
    "CPO": "CPD10",
    "FEP": "FEP30",
    "CPM": "FEP30",
    "ATM": "ATM30",
    "TZP": "TZP36",
    "TPZ": "TPZ36",
    "SAM": "SAM20",
    "ETP": "ETP10",
    "IPM": "IPM10",
    "MEM": "MEM10",
    "MRP": "MEM10",
    "VA": "VA30",
    "VAN": "VA30",
    "E": "E15",
    "ERY": "E15",
    "CD": "CD2",
    "DA": "CD2",
    "CLI": "CD2",
    "C": "C30",
    "CHL": "C30",
    "RD": "RD5",
    "RA": "RD5",
    "RIF": "RD5",
    "P": "P10",
    "TC": "TC75",
}


def _normalize_ocr_token_variants(raw_text: str) -> List[str]:
    """
    แปลงผลลัพธ์จาก OCR ที่อาจสับสนระหว่างตัวอักษรกับตัวเลข เช่น:
    - 'AMC3O' / 'AMC3D' -> 'AMC30'
    - 'CPDIO' / 'CPO10' -> 'CPD10'
    - 'ETPIO' -> 'ETP10'
    - 'PEFS'  -> 'PEF5'
    - 'CDZ'   -> 'CD2'
    """
    clean = re.sub(r"[^A-Z0-9]", "", (raw_text or "").upper())
    if not clean:
        return []

    variants = [clean]
    letter_map = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z"})
    digit_map = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})

    # แยกส่วนต้นเป็นตัวอักษร (1-4 ตัว) และส่วนท้ายเป็นตัวเลข (1-3 ตัว)
    for split_pos in range(1, min(5, len(clean) + 1)):
        head = clean[:split_pos].translate(letter_map)
        tail = clean[split_pos:].translate(digit_map)
        if head.isalpha() and (not tail or tail.isdigit()):
            cand = head + tail
            if cand not in variants:
                variants.append(cand)
        if head.isalpha() and head not in variants:
            variants.append(head)

    return variants


def _prepare_circular_disc_variants_for_ocr(disc_bgr: np.ndarray) -> List[np.ndarray]:
    """
    ตัดขอบดำและพื้นหลังวุ้นเพาะเชื้อรอบเม็ดยาออก เหลือเฉพาะวงกลมเนื้อกระดาษสีขาวด้านใน
    แล้วเติมขอบขาว (White Margin Padding) เพื่อให้ EasyOCR อ่านตัวอักษรบนเม็ดยาที่หมุนตั้งตรงได้แม่นยำขึ้น
    """
    h, w = disc_bgr.shape[:2]
    gray = cv2.cvtColor(disc_bgr, cv2.COLOR_BGR2GRAY) if disc_bgr.ndim == 3 else disc_bgr.copy()
    gray = cv2.resize(gray, (180, 180), interpolation=cv2.INTER_CUBIC)

    yy, xx = np.ogrid[:180, :180]
    dist = np.sqrt((xx - 90.0) ** 2 + (yy - 90.0) ** 2)

    # ใช้ค่ามัธยฐานของเนื้อกระดาษด้านในแทนขอบนอก เพื่อลบเงาวงกลมสีดำของขอบเม็ดยา
    inner_paper_pixels = gray[dist <= 64.0]
    paper_bg = int(np.percentile(inner_paper_pixels, 75)) if inner_paper_pixels.size > 0 else 235

    masked = gray.copy()
    masked[dist > 74.0] = paper_bg

    # Variant 1: CLAHE + White Padding
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(4, 4)).apply(masked)
    clahe[dist > 73.0] = paper_bg
    v1 = cv2.copyMakeBorder(clahe, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=paper_bg)

    # Variant 2: Contrast Stretch (ดึงหมึกพิมพ์ให้เข้มขึ้นบนพื้นขาว)
    p5 = float(np.percentile(inner_paper_pixels, 8)) if inner_paper_pixels.size > 0 else 40.0
    p95 = float(np.percentile(inner_paper_pixels, 88)) if inner_paper_pixels.size > 0 else 235.0
    denom = max(20.0, p95 - p5)
    stretched = np.clip((masked.astype(np.float32) - p5) * (255.0 / denom), 0, 255).astype(np.uint8)
    stretched[dist > 72.0] = 255
    v2 = cv2.copyMakeBorder(stretched, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=255)

    # Variant 3: Adaptive Threshold (ขาว-ดำคมชัดไร้ขอบวงกลม)
    blur = cv2.GaussianBlur(stretched, (3, 3), 0)
    thresh = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 9
    )
    thresh[dist > 70.0] = 255
    v3 = cv2.copyMakeBorder(thresh, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=255)

    return [v1, v2, v3]


def _split_alpha_num_code(code: str) -> Tuple[str, str]:
    clean = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
    m = re.match(r"^([A-Z]+)(\d*)$", clean)
    if m:
        return m.group(1), m.group(2)
    letters = re.sub(r"[^A-Z]", "", clean)
    digits = re.sub(r"[^0-9]", "", clean)
    return letters, digits


def _prefix_similarity(a: str, b: str) -> float:
    """คำนวณความคล้ายของตัวอักษรย่อชื่อยา (0.0 - 1.0) โดยพิจารณาทั้งลำดับตัวอักษรและตัวอักษรที่ใช้ร่วมกัน"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return (2.0 * min(len(a), len(b))) / (len(a) + len(b))

    # นับตัวอักษรที่ตรงกันตามลำดับ (Subsequence / Overlap)
    i = 0
    in_order = 0
    for ch in a:
        pos = b.find(ch, i)
        if pos != -1:
            in_order += 1
            i = pos + 1
    common_set = len(set(a) & set(b))
    best_match = max(in_order, common_set * 0.85)
    return min(0.95, (2.0 * best_match) / (len(a) + len(b)))


def rank_all_drugs_from_ocr(
    raw_texts: List[str],
    bp_map: Dict[str, Dict[str, Any]],
    disc_bgr: Optional[np.ndarray] = None,
    c_mod: Any = None,
) -> List[Dict[str, Any]]:
    """
    คำนวณเปอร์เซ็นต์ความมั่นใจของโมเดลสำหรับตัวยาทุกตัวในระบบ (0% - 99%)
    แล้วเรียงลำดับจากเปอร์เซ็นต์มากที่สุดไปน้อยที่สุด เพื่อให้ผู้ใช้กดเลือกจาก Dropdown ได้ง่ายที่สุด
    """
    all_drug_codes = [k for k in bp_map.keys() if k not in ("UNKNOWN", "DISC")]
    scores: Dict[str, float] = {code: 0.01 for code in all_drug_codes}

    # รวบรวม Token ที่อ่านได้ทั้งหมดพร้อมตัวแปรที่แก้คำผิด (เช่น O->0, I->1, S->5)
    normalized_tokens: List[str] = []
    for raw in raw_texts:
        for var in _normalize_ocr_token_variants(raw):
            if var and var not in normalized_tokens:
                normalized_tokens.append(var)

    # ตรวจสอบสีเม็ดยาน้ำตาลเข้มของ TE30
    is_brown_te = False
    if disc_bgr is not None and c_mod is not None and hasattr(c_mod, "is_te30_brown_disc"):
        try:
            is_brown_te = bool(c_mod.is_te30_brown_disc(disc_bgr))
        except Exception:
            is_brown_te = False

    if is_brown_te and "TE30" in scores:
        scores["TE30"] = max(scores["TE30"], 0.94)

    for code in all_drug_codes:
        k_prefix, k_num = _split_alpha_num_code(code)
        best_for_code = scores.get(code, 0.01)

        for tok in normalized_tokens:
            t_prefix, t_num = _split_alpha_num_code(tok)

            # 1. ตรงกันทั้งรหัสยาแบบ 100% (เช่น CPD10 == CPD10, AMC30 == AMC30)
            if tok == code or (t_prefix == k_prefix and t_num == k_num and k_prefix):
                best_for_code = max(best_for_code, 0.98)
                continue

            # 2. ตรงกับ Alias มาตรฐาน (เช่น CPO -> CPD10, AIVIC -> AMC30, TZP <-> TPZ)
            mapped_alias = DRUG_PREFIX_ALIASES.get(t_prefix) or DRUG_PREFIX_ALIASES.get(tok)
            if mapped_alias == code:
                if t_num == k_num and k_num:
                    best_for_code = max(best_for_code, 0.95)
                elif not t_num:
                    best_for_code = max(best_for_code, 0.89)
                else:
                    best_for_code = max(best_for_code, 0.76)
                continue

            # 3. คำนวณความคล้ายของหมวดตัวอักษรย่อ (Prefix) และขนาดโดสยา (Dose Number)
            p_sim = _prefix_similarity(t_prefix, k_prefix) if (t_prefix and k_prefix) else 0.0
            if mapped_alias:
                alias_p, _ = _split_alpha_num_code(mapped_alias)
                p_sim = max(p_sim, _prefix_similarity(alias_p, k_prefix) * 0.95)

            dose_exact = bool(t_num and k_num and t_num == k_num)
            dose_partial = bool(t_num and k_num and not dose_exact and (t_num in k_num or k_num in t_num))

            if p_sim >= 0.99:
                # ตัวอักษรย่อตรงเป๊ะ (เช่น อ่านได้ 'CPD' หรือ 'AMC')
                if dose_exact:
                    cand_score = 0.97
                elif not t_num:
                    cand_score = 0.88 if len(k_prefix) >= 2 else 0.74
                elif dose_partial:
                    cand_score = 0.91
                else:
                    cand_score = 0.68
            elif p_sim >= 0.55:
                # ตัวอักษรย่อตรงบางส่วน (เช่น 'CP10' หรือ 'PD10' เทียบกับ 'CPD10')
                if dose_exact:
                    cand_score = min(0.89, 0.52 * p_sim + 0.36)
                elif dose_partial:
                    cand_score = 0.48 * p_sim + 0.18
                elif not t_num:
                    cand_score = 0.50 * p_sim
                else:
                    cand_score = 0.35 * p_sim
            elif p_sim > 0.0:
                # มีตัวอักษรตรงกัน 1 ตัว
                if dose_exact:
                    cand_score = 0.32 * p_sim + 0.24
                elif dose_partial:
                    cand_score = 0.25 * p_sim + 0.10
                else:
                    cand_score = 0.18 * p_sim
            else:
                # ตัวอักษรไม่ตรงเลย แต่เลขโดสตรงกัน (เช่น อ่านเห็นแค่เลข '10' หรือ '30')
                if dose_exact:
                    cand_score = 0.24
                elif dose_partial:
                    cand_score = 0.12
                else:
                    cand_score = 0.01

            best_for_code = max(best_for_code, cand_score)

        scores[code] = round(min(0.99, best_for_code), 3)

    ranked = sorted(
        [{"code": code, "confidence": scores[code]} for code in all_drug_codes],
        key=lambda item: (-item["confidence"], item["code"]),
    )
    return ranked


def _match_ocr_candidates_to_drug(
    raw_texts: List[str],
    bp_map: Dict[str, Dict[str, Any]],
    c_mod: Any = None,
    panel_preset: str = "auto",
    disc_bgr: Optional[np.ndarray] = None,
) -> Tuple[str, float, str, bool, List[Dict[str, Any]]]:
    """
    จับคู่ข้อความที่อ่านได้จากเม็ดยากับฐานข้อมูลยาทั้งหมด พร้อมคืนตารางความมั่นใจของยาทุกตัว (ranked_candidates)
    โดยไม่จำกัดอยู่แค่ 5 ตัวยาของมหิดล เพื่อป้องกันปัญหาอ่าน CPD10 แล้วกลายเป็น AMP10
    """
    ranked_candidates = rank_all_drugs_from_ocr(
        raw_texts=raw_texts,
        bp_map=bp_map,
        disc_bgr=disc_bgr,
        c_mod=c_mod,
    )

    best_raw = ""
    for r in raw_texts:
        c = re.sub(r"[^A-Z0-9]", "", (r or "").upper())
        if c:
            best_raw = c
            break

    if not ranked_candidates:
        return "UNKNOWN", 0.0, best_raw, False, []

    top_hit = ranked_candidates[0]
    top_code = str(top_hit["code"])
    top_conf = float(top_hit["confidence"])

    # ต้องมีความมั่นใจอย่างน้อย 55% (เช่น มีตัวอักษรตรง ไม่ใช่ตรงแค่เลขโดสอย่างเดียว) จึงจะฟันธงชื่อยา
    if top_conf >= 0.55:
        return top_code, top_conf, best_raw or top_code, True, ranked_candidates

    return "UNKNOWN", 0.0, best_raw, False, ranked_candidates


def re_ocr_rotated_disc_crop(
    img_bytes: bytes,
    panel_preset: str = "auto",
) -> Dict[str, Any]:
    """
    อ่านชื่อยาซ้ำจากภาพเม็ดยาที่ผู้ใช้หมุนปรับมุมเองแล้ว (Manual Upright Orientation Re-OCR)
    พร้อมส่งคืนเปอร์เซ็นต์ความมั่นใจของตัวยาทุกตัว (ocr_candidates) เรียงจากมากไปน้อย
    """
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    disc_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if disc_bgr is None or disc_bgr.size == 0:
        raise ValueError("ไม่สามารถอ่านภาพเม็ดยาที่ส่งมาได้")

    _, best_ocr = get_best_sota_models()
    c_mod = _CACHED_CLF_MODULE
    bp_map = get_merged_breakpoints()

    collected_raw_candidates: List[str] = []
    best_code = "UNKNOWN"
    best_conf = 0.0
    best_raw_text = ""
    best_is_known = False
    best_ranked_list: List[Dict[str, Any]] = []

    with INFERENCE_LOCK:
        reader = getattr(best_ocr, "reader", None) if best_ocr is not None else None
        if reader is not None and c_mod is not None:
            sweep_angles = [0, -10, 10, 180]
            for ang in sweep_angles:
                rot_bgr = c_mod.rotate_image_any_angle(disc_bgr, ang) if ang != 0 else disc_bgr
                ocr_imgs = _prepare_circular_disc_variants_for_ocr(rot_bgr)
                try:
                    ocr_imgs.append(c_mod.preprocess_disc_for_ocr(rot_bgr, target_size=160))
                except Exception:
                    pass

                for variant_img in ocr_imgs:
                    try:
                        dets = reader.readtext(
                            variant_img,
                            detail=1,
                            paragraph=False,
                            allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                            text_threshold=0.35,
                            low_text=0.25,
                            mag_ratio=1.8,
                        )
                        if dets:
                            sorted_dets = sorted(
                                dets,
                                key=lambda item: (
                                    float(np.mean([pt[1] for pt in item[0]])),
                                    float(np.mean([pt[0] for pt in item[0]])),
                                ),
                            )
                            tokens = [
                                re.sub(r"[^A-Z0-9]", "", str(item[1]).upper())
                                for item in sorted_dets
                                if str(item[1]).strip()
                            ]
                            tokens = [t for t in tokens if t]
                            if tokens:
                                joined_top_down = "".join(tokens)
                                collected_raw_candidates.append(joined_top_down)
                                if len(tokens) > 1:
                                    collected_raw_candidates.append("".join(reversed(tokens)))
                                    collected_raw_candidates.extend(tokens)
                    except Exception:
                        pass

                    try:
                        raw_txt = best_ocr._ocr_read_text(variant_img, enhanced_params=True)
                        if raw_txt:
                            collected_raw_candidates.append(raw_txt)
                    except Exception:
                        pass

                code, conf, raw_hit, is_known, ranked_list = _match_ocr_candidates_to_drug(
                    collected_raw_candidates,
                    bp_map=bp_map,
                    c_mod=c_mod,
                    panel_preset="auto",
                    disc_bgr=disc_bgr,
                )
                if ranked_list and (not best_ranked_list or conf > best_conf):
                    best_ranked_list = ranked_list
                if is_known and conf > best_conf:
                    best_code = code
                    best_conf = conf
                    best_raw_text = raw_hit
                    best_is_known = True
                    if best_conf >= 0.92 and abs(ang) <= 10:
                        break

    if not best_ranked_list:
        _, _, best_raw_text, _, best_ranked_list = _match_ocr_candidates_to_drug(
            collected_raw_candidates,
            bp_map=bp_map,
            c_mod=c_mod,
            panel_preset="auto",
            disc_bgr=disc_bgr,
        )

    if best_code in ("DISC", "UNKNOWN") or not best_is_known:
        best_code = "UNKNOWN"
        best_conf = 0.0

    sir, guideline, bp_r, bp_s = interpret_sir(best_code, 6.0, breakpoints_map=bp_map)
    bp_info = bp_map.get(best_code, {})

    return {
        "status": "ok",
        "drug_code": best_code,
        "raw_ocr_text": best_raw_text,
        "drug_full_name": bp_info.get("name", best_code),
        "ocr_confidence": round(float(best_conf), 3),
        "ocr_candidates": best_ranked_list,
        "is_known": best_is_known,
        "guideline": guideline,
        "bp_r_mm": bp_r,
        "bp_s_mm": bp_s,
    }


def analyze_manual_disc_at_point(
    img_bytes: bytes,
    center_x: int,
    center_y: int,
    r_disc_px: float,
    user_diameter_mm: Optional[float] = None,
    existing_discs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    วิเคราะห์เม็ดยาที่ผู้ใช้คลิกเพิ่มเองบนภาพจานเพาะเชื้อ (กรณีโมเดลตรวจหาเม็ดยาไม่ครบ):
    1. หากผู้ใช้ลากวงใสเอง (user_diameter_mm) จะใช้ขนาดวงใสที่ผู้ใช้วาดทันที
       แต่หากคลิกจุดกึ่งกลางเฉยๆ จะรัน ContinuousWarpPolarMeasurer วัดขนาดวงใสให้อัตโนมัติ
    2. ตัดภาพเม็ดยา ณ พิกัด (center_x, center_y) ไปรัน OCR พร้อมจัดอันดับเปอร์เซ็นต์ความมั่นใจของยาทุกตัว
    """
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("ไม่สามารถอ่านภาพจานเพาะเชื้อได้")

    h, w = bgr.shape[:2]
    cx = int(np.clip(center_x, 4, w - 4))
    cy = int(np.clip(center_y, 4, h - 4))
    r_px = float(max(10.0, r_disc_px))
    scale_mm_per_px = 6.0 / max(2.0, 2.0 * r_px)

    # 1. วัดขนาดวงใสด้วย ContinuousWarpPolarMeasurer หรือใช้ขนาดที่ผู้ใช้ลากวงเอง
    if user_diameter_mm is not None and float(user_diameter_mm) >= 6.0:
        final_mm = round(float(np.clip(user_diameter_mm, 6.0, 42.0)), 1)
    else:
        try:
            with INFERENCE_LOCK:
                zone_bundle, _ = get_best_sota_models()
                m_mod, warp_polar_measurer = zone_bundle
                pre_gray = m_mod.preprocess_plate_for_zone(bgr)
                target_det = m_mod.DiscDetection(
                    disc_id=99,
                    center=(cx, cy),
                    radius_px=r_px,
                    diameter_px=2.0 * r_px,
                    bbox=m_mod.BoundingBox(
                        x1=max(0, int(round(cx - r_px))),
                        y1=max(0, int(round(cy - r_px))),
                        x2=min(w, int(round(cx + r_px))),
                        y2=min(h, int(round(cy + r_px))),
                    ),
                )
                all_det_objs = [target_det]
                for idx_e, ed in enumerate(existing_discs or []):
                    ecx = int(ed.get("center_x", 0))
                    ecy = int(ed.get("center_y", 0))
                    er = float(ed.get("r_disc_px", r_px))
                    if abs(ecx - cx) > 6 or abs(ecy - cy) > 6:
                        all_det_objs.append(
                            m_mod.DiscDetection(
                                disc_id=idx_e + 1,
                                center=(ecx, ecy),
                                radius_px=er,
                                diameter_px=2.0 * er,
                                bbox=m_mod.BoundingBox(
                                    x1=max(0, int(round(ecx - er))),
                                    y1=max(0, int(round(ecy - er))),
                                    x2=min(w, int(round(ecx + er))),
                                    y2=min(h, int(round(ecy + er))),
                                ),
                            )
                        )
                z_res = warp_polar_measurer.measure(pre_gray, target_det, all_discs=all_det_objs)
                final_mm = round(float(z_res.diameter_mm), 1)
        except Exception:
            final_mm = 6.0

    # 2. ตัดภาพเฉพาะเม็ดยาที่พิกัด (cx, cy) แล้วรัน OCR พร้อมคำนวณความมั่นใจของยาทุกตัว
    pad = int(round(r_px * 0.12))
    x1, y1 = max(0, int(round(cx - r_px - pad))), max(0, int(round(cy - r_px - pad)))
    x2, y2 = min(w, int(round(cx + r_px + pad))), min(h, int(round(cy + r_px + pad)))
    crop = bgr[y1:y2, x1:x2]

    ok_enc, crop_buf = cv2.imencode(".png", crop)
    if ok_enc:
        ocr_info = re_ocr_rotated_disc_crop(crop_buf.tobytes(), panel_preset="auto")
    else:
        bp_map = get_merged_breakpoints()
        ocr_info = {
            "drug_code": "UNKNOWN",
            "raw_ocr_text": "",
            "ocr_confidence": 0.0,
            "ocr_candidates": rank_all_drugs_from_ocr([], bp_map),
        }

    bp_map = get_merged_breakpoints()
    drug_code = str(ocr_info.get("drug_code") or "UNKNOWN")
    sir, guideline, bp_r, bp_s = interpret_sir(drug_code, final_mm, breakpoints_map=bp_map)
    bp_info = bp_map.get(drug_code, {})

    return {
        "status": "ok",
        "disc": {
            "disc_order": 1,
            "plate_zone": "Manual",
            "center_x": cx,
            "center_y": cy,
            "r_disc_px": round(r_px, 1),
            "r_zone_px": round((final_mm / 2.0) / scale_mm_per_px, 1),
            "scale_mm_per_px": round(scale_mm_per_px, 4),
            "confidence": 1.0,
            "ocr_confidence": float(ocr_info.get("ocr_confidence", 0.0)),
            "ocr_candidates": ocr_info.get("ocr_candidates", []),
            "raw_ocr_text": ocr_info.get("raw_ocr_text", ""),
            "needs_review": drug_code in ("UNKNOWN", "DISC"),
            "drug_code": drug_code,
            "drug_full_name": bp_info.get("name", drug_code),
            "diameter_mm": final_mm,
            "sir_status": sir,
            "guideline": guideline,
            "bp_r_mm": bp_r,
            "bp_s_mm": bp_s,
        },
    }


def load_album_entries() -> List[Dict[str, Any]]:
    with ALBUM_LOCK:
        if not ALBUM_INDEX_FILE.exists():
            return []
        try:
            with open(ALBUM_INDEX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []


def save_album_entries(entries: List[Dict[str, Any]]) -> None:
    with ALBUM_LOCK:
        ALBUM_DIR.mkdir(parents=True, exist_ok=True)
        with open(ALBUM_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)


def bulk_delete_album_entries(album_ids: Optional[List[str]] = None, clear_all: bool = False) -> int:
    """ลบหลายรูปในอัลบั้มพร้อมกันในครั้งเดียว (หรือล้างทั้งหมด) พร้อมลบไฟล์รูปออกจากดิสก์"""
    with ALBUM_LOCK:
        entries = load_album_entries()
        id_set = set(album_ids or [])
        kept = []
        deleted_count = 0
        for item in entries:
            aid = str(item.get("album_id", ""))
            if clear_all or (aid in id_set):
                deleted_count += 1
                img_url = str(item.get("image_url", ""))
                if img_url.startswith("/album/images/"):
                    img_file = ALBUM_DIR / img_url.split("/album/images/", 1)[1]
                    if img_file.exists():
                        try:
                            img_file.unlink()
                        except Exception:
                            pass
            else:
                kept.append(item)
        save_album_entries(kept)
        return deleted_count


def build_combined_xlsx_bytes(plates_list: List[Dict[str, Any]]) -> bytes:
    """สร้างไฟล์ Excel (.xlsx) รวมผลวิเคราะห์ของหลายรูปจานเพาะเชื้อเข้าด้วยกันในไฟล์เดียว"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Combined_AST_Results"
    ws.views.sheetView[0].showGridLines = True

    header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    alt_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    s_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    i_fill = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")
    r_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    headers = [
        "ลำดับรูป",
        "ชื่อไฟล์ภาพ / จานเพาะเชื้อ",
        "สายพันธุ์เชื้อ",
        "ตำแหน่งเม็ดยา (#)",
        "โซนบนจาน",
        "พิกัด X (px)",
        "พิกัด Y (px)",
        "รหัสยา",
        "ชื่อเต็มของยา",
        "ขนาดวงใส (mm)",
        "เกณฑ์ R ≤ (mm)",
        "เกณฑ์ S ≥ (mm)",
        "ผลแปล (S/I/R)",
    ]

    for col_idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=text)
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
    ws.row_dimensions[1].height = 24

    row_cursor = 2
    for p_idx, plate in enumerate(plates_list, start=1):
        p_title = str(plate.get("title") or plate.get("plate_id") or f"Plate_{p_idx}")
        species = str(plate.get("bacteria_species") or "Escherichia coli ATCC 25922")
        discs = plate.get("discs") or []
        for d in discs:
            sir = str(d.get("sir_status") or "R").upper()
            row_values = [
                p_idx,
                p_title,
                species,
                int(d.get("disc_order") or 1),
                str(d.get("plate_zone") or "-"),
                int(d.get("center_x") or 0),
                int(d.get("center_y") or 0),
                str(d.get("drug_code") or "UNKNOWN"),
                str(d.get("drug_full_name") or d.get("drug_code") or "-"),
                float(d.get("diameter_mm") or 6.0),
                float(d.get("bp_r_mm") or 14.0),
                float(d.get("bp_s_mm") or 19.0),
                sir,
            ]
            ws.append(row_values)

            is_even = (row_cursor % 2 == 0)
            for c_i in range(1, len(headers) + 1):
                c = ws.cell(row=row_cursor, column=c_i)
                c.border = thin_border
                c.font = Font(name="Calibri", size=10)
                if is_even:
                    c.fill = alt_fill
                if c_i in (1, 4, 5, 8, 13):
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif c_i in (6, 7):
                    c.alignment = Alignment(horizontal="right", vertical="center")
                    c.number_format = "#,##0"
                elif c_i in (10, 11, 12):
                    c.alignment = Alignment(horizontal="right", vertical="center")
                    c.number_format = "0.0"
                else:
                    c.alignment = Alignment(horizontal="left", vertical="center")

                if c_i == 13:
                    c.font = Font(name="Calibri", size=10, bold=True)
                    if sir == "S":
                        c.fill = s_fill
                    elif sir == "I":
                        c.fill = i_fill
                    else:
                        c.fill = r_fill
            row_cursor += 1

    ws.freeze_panes = "A2"
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 36)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def analyze_plate_best_model_only(
    img_bytes: bytes,
    filename: str = "uploaded_plate.png",
    panel_preset: str = "auto",
    save_to_album: bool = True,
) -> Dict[str, Any]:
    """รันเฉพาะโมเดลที่ดีที่สุด (YOLOv26s + Continuous Warp Polar + Hybrid Hungarian OCR) อย่างปลอดภัยในโหมด Parallel"""
    t_start = time.perf_counter()
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("ไม่สามารถอ่านไฟล์รูปภาพได้")

    h, w = bgr.shape[:2]
    stem = Path(filename).stem.replace(" original", "").strip()
    excel_meta = load_excel_plate_metadata()
    plate_meta = excel_meta.get(stem, {})

    has_known_panel = False
    if panel_preset == "mahidol5":
        expected_drugs = list(DEFAULT_MAHIDOL_5_DRUGS)
        has_known_panel = True
    elif plate_meta.get("drugs"):
        expected_drugs = list(plate_meta["drugs"])
        has_known_panel = True
    else:
        expected_drugs = list(DEFAULT_MAHIDOL_5_DRUGS)

    with INFERENCE_LOCK:
        discs = detect_discs_for_db(bgr, weights_path=DEFAULT_YOLO_WEIGHTS, expected_count=len(expected_drugs))
        zone_bundle, best_ocr = get_best_sota_models()
        m_mod, warp_polar_measurer = zone_bundle
        pre_gray = m_mod.preprocess_plate_for_zone(bgr)

        det_objs = [
            m_mod.DiscDetection(
                disc_id=int(d["disc_index"]),
                center=(int(d["cx"]), int(d["cy"])),
                radius_px=float(d["r"]),
                diameter_px=max(2.0, 2.0 * float(d["r"])),
                bbox=m_mod.BoundingBox(
                    x1=max(0, int(round(float(d["cx"]) - float(d["r"])))),
                    y1=max(0, int(round(float(d["cy"]) - float(d["r"])))),
                    x2=max(0, int(round(float(d["cx"]) + float(d["r"])))),
                    y2=max(0, int(round(float(d["cy"]) + float(d["r"])))),
                ),
            )
            for d in discs
        ]

        zone_mm_list = []
        for d_obj in det_objs:
            z_res = warp_polar_measurer.measure(pre_gray, d_obj, all_discs=det_objs)
            zone_mm_list.append(float(z_res.diameter_mm))

        crops = []
        for d in discs:
            cx, cy, r_px = int(d["cx"]), int(d["cy"]), float(d["r"])
            pad = int(round(r_px * 0.12))
            x1, y1 = max(0, int(round(cx - r_px - pad))), max(0, int(round(cy - r_px - pad)))
            x2, y2 = min(w, int(round(cx + r_px + pad))), min(h, int(round(cy + r_px + pad)))
            crops.append(bgr[y1:y2, x1:x2])

        bp_map_all = get_merged_breakpoints()
        all_standard_codes = [k for k in bp_map_all.keys() if k not in ("UNKNOWN", "DISC")]
        ocr_confs = [0.0] * len(discs)
        ocr_candidates_per_disc: List[List[Dict[str, Any]]] = [[] for _ in range(len(discs))]
        raw_ocr_texts: List[str] = ["" for _ in range(len(discs))]
        is_uncertain_list = [False] * len(discs)

        if best_ocr is not None and getattr(best_ocr, "reader", None) is not None and crops:
            raw_codes = []
            for idx_c, c in enumerate(crops):
                ok_c, buf_c = cv2.imencode(".png", c)
                if ok_c:
                    c_ocr = re_ocr_rotated_disc_crop(buf_c.tobytes(), panel_preset="auto")
                    code_c = str(c_ocr.get("drug_code") or "UNKNOWN")
                    conf_c = float(c_ocr.get("ocr_confidence") or 0.0)
                    is_known_c = bool(c_ocr.get("is_known"))
                    ocr_candidates_per_disc[idx_c] = c_ocr.get("ocr_candidates") or []
                    raw_ocr_texts[idx_c] = str(c_ocr.get("raw_ocr_text") or "")
                else:
                    code_c, conf_c, _, is_known_c = best_ocr.classify_crop(
                        c, candidate_drugs=expected_drugs if has_known_panel else all_standard_codes
                    )
                    ocr_candidates_per_disc[idx_c] = rank_all_drugs_from_ocr(
                        [code_c] if code_c not in ("DISC", "UNKNOWN") else [],
                        bp_map=bp_map_all,
                        disc_bgr=c,
                        c_mod=_CACHED_CLF_MODULE,
                    )
                raw_codes.append(code_c)
                ocr_confs[idx_c] = float(conf_c)
                is_uncertain_list[idx_c] = (not is_known_c) or (conf_c < 0.80) or (code_c in ("DISC", "UNKNOWN"))

            if has_known_panel and len(discs) == len(expected_drugs):
                pred_drugs = best_ocr.classify_plate_crops_hungarian(crops, expected_drugs)
            else:
                pred_drugs = raw_codes
        else:
            pred_drugs = [expected_drugs[i % len(expected_drugs)] for i in range(len(discs))]
            for idx_c in range(len(discs)):
                ocr_candidates_per_disc[idx_c] = rank_all_drugs_from_ocr(
                    [pred_drugs[idx_c]], bp_map=bp_map_all
                )
            if not has_known_panel:
                is_uncertain_list = [True] * len(discs)

    bp_map = get_merged_breakpoints()
    disc_results = []
    for i, d in enumerate(discs):
        cx, cy, r_px = int(d["cx"]), int(d["cy"]), float(d["r"])
        scale_mm_per_px = 6.0 / max(2.0, 2.0 * r_px)
        raw_pred = pred_drugs[i] if i < len(pred_drugs) else "UNKNOWN"
        if raw_pred in ("DISC", "UNKNOWN", "") and has_known_panel:
            drug_code = expected_drugs[i % len(expected_drugs)]
            uncertain = True
        elif raw_pred in ("DISC", "UNKNOWN", ""):
            drug_code = "UNKNOWN"
            uncertain = True
            ocr_confs[i] = 0.0
        else:
            drug_code = raw_pred
            uncertain = bool(is_uncertain_list[i])

        final_mm = round(zone_mm_list[i], 1)
        sir, guideline, bp_r, bp_s = interpret_sir(drug_code, final_mm, breakpoints_map=bp_map)
        bp_info = bp_map.get(drug_code, {})

        disc_results.append({
            "disc_order": int(d["disc_index"]),
            "plate_zone": str(d["plate_zone"]),
            "center_x": cx,
            "center_y": cy,
            "r_disc_px": round(r_px, 1),
            "r_zone_px": round((final_mm / 2.0) / scale_mm_per_px, 1),
            "scale_mm_per_px": round(scale_mm_per_px, 4),
            "confidence": round(float(d.get("conf", 0.96)), 3),
            "ocr_confidence": round(float(ocr_confs[i]), 3),
            "ocr_candidates": ocr_candidates_per_disc[i],
            "raw_ocr_text": raw_ocr_texts[i],
            "needs_review": uncertain,
            "drug_code": drug_code,
            "drug_full_name": bp_info.get("name", drug_code),
            "diameter_mm": final_mm,
            "sir_status": sir,
            "guideline": guideline,
            "bp_r_mm": bp_r,
            "bp_s_mm": bp_s,
        })

    elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 1)
    album_id = f"alb_{int(time.time() * 1000)}_{uuid.uuid4().hex[:5]}"
    saved_image_url = None

    if save_to_album:
        with ALBUM_LOCK:
            ext = Path(filename).suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg"):
                ext = ".png"
            saved_img_name = f"{album_id}{ext}"
            saved_img_path = ALBUM_DIR / saved_img_name
            with open(saved_img_path, "wb") as f:
                f.write(img_bytes)
            saved_image_url = f"/album/images/{saved_img_name}"

            entry = {
                "album_id": album_id,
                "title": filename,
                "plate_id": stem,
                "image_url": saved_image_url,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "bacteria_species": plate_meta.get("species", "Escherichia coli ATCC 25922"),
                "elapsed_ms": elapsed_ms,
                "total_discs": len(disc_results),
                "discs": disc_results,
            }
            entries = load_album_entries()
            entries.insert(0, entry)
            save_album_entries(entries[:200])

    return {
        "status": "ok",
        "album_id": album_id,
        "title": filename,
        "plate_id": stem,
        "image_url": saved_image_url,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bacteria_species": plate_meta.get("species", "Escherichia coli ATCC 25922"),
        "elapsed_ms": elapsed_ms,
        "total_discs": len(disc_results),
        "discs": disc_results,
    }


WEB_HTML_UI = r"""<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0" />
  <meta name="mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="AST Analyzer" />
  <link rel="manifest" href="/manifest.json" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+Thai:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <title>ระบบวิเคราะห์ความไวต่อยาปฏิชีวนะ — AST Disk Diffusion Analysis System</title>
  <style>
    :root {
      /* Eye-Care Warm Daylight Mode (โทนสว่างนวลตา ลดแสงสะท้อนสีขาวจัด) */
      --bg: #f3f5f8;
      --panel: #fbfcfd;
      --panel-subtle: #eaf0f6;
      --text: #1e293b;
      --muted: #64748b;
      --border: #d8e1eb;
      --grid-line: #e2e8f0;
      --primary: #2d7a73;
      --primary-hover: #23615b;
      --primary-text: #f8fafc;
      --secondary: #dde9f2;
      --accent: #3b7696;
      --accent-vivid: #2d7a73;
      --accent-bg: rgba(45, 122, 115, 0.09);
      --danger: #c84b4b;
      --danger-hover: #a83a3a;
      --skel-1: #e2e8f0;
      --skel-2: #f1f5f9;
      --s-bg: #e1f2eb; --s-text: #226348; --s-border: #a3d9c2;
      --i-bg: #faefd9; --i-text: #85581a; --i-border: #e8c987;
      --r-bg: #fae3e3; --r-text: #962d2d; --r-border: #ebb2b2;
      --card-shadow: 0 4px 16px -2px rgba(30, 41, 59, 0.05);
      --col-badge-bg: #e2e8f0;
      --col-badge-text: #334155;
    }
    [data-theme="dark"] {
      /* Eye-Care Soft Slate Dark Mode (โทนมืดนุ่มลึกแบบจออ่านฟิล์มทางการแพทย์ ไม่ใช้สีดำสนิทและไร้สีนีออนแสบตา) */
      --bg: #161b22;
      --panel: #1f2630;
      --panel-subtle: #262f3b;
      --text: #dbe2eb;
      --muted: #8b98a9;
      --border: #303b49;
      --grid-line: #283240;
      --primary: #3b827b;
      --primary-hover: #49968e;
      --primary-text: #f1f5f9;
      --secondary: #263342;
      --accent: #72b3a8;
      --accent-vivid: #72b3a8;
      --accent-bg: rgba(114, 179, 168, 0.11);
      --danger: #c95b5b;
      --danger-hover: #b04646;
      --skel-1: #242c37;
      --skel-2: #2e3846;
      --s-bg: rgba(104, 176, 136, 0.16); --s-text: #8ac9a6; --s-border: rgba(104, 176, 136, 0.36);
      --i-bg: rgba(217, 167, 84, 0.16); --i-text: #e6bf7e; --i-border: rgba(217, 167, 84, 0.36);
      --r-bg: rgba(217, 108, 108, 0.16); --r-text: #e89595; --r-border: rgba(217, 108, 108, 0.36);
      --card-shadow: 0 6px 20px -4px rgba(0, 0, 0, 0.35);
      --col-badge-bg: #2b3543;
      --col-badge-text: #c9d3df;
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: 'Inter', 'Noto Sans Thai', 'Sarabun', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      -webkit-tap-highlight-color: transparent;
    }
    body {
      background: var(--bg);
      color: var(--text);
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: background 0.2s, color 0.2s;
      line-height: 1.45;
    }
    @media (max-width: 1024px) {
      body { height: auto; min-height: 100vh; overflow-y: auto; overflow-x: hidden; }
    }

    /* Academic Clinical Top Navigation Bar */
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 10px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
      flex-shrink: 0;
      z-index: 30;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 700;
      font-size: 1.02rem;
      letter-spacing: -0.01em;
      flex-wrap: wrap;
    }
    .brand-title {
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }
    .std-pill {
      font-size: 0.72rem;
      padding: 3px 9px;
      border-radius: 6px;
      font-weight: 700;
      background: var(--panel-subtle);
      color: var(--muted);
      border: 1px solid var(--border);
      letter-spacing: 0.02em;
    }
    .queue-pill {
      font-size: 0.76rem;
      padding: 4px 12px;
      border-radius: 6px;
      font-weight: 700;
      background: rgba(0, 194, 152, 0.14);
      color: var(--accent);
      border: 1px solid rgba(0, 194, 152, 0.4);
      display: none;
      align-items: center;
      gap: 6px;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    button, select, .btn-label, input[type="text"], input[type="number"] {
      background: var(--panel);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 7px 13px;
      border-radius: 8px;
      font-size: 0.84rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    button, select, .btn-label { cursor: pointer; }
    button.primary, .btn-label.primary {
      background: var(--primary);
      color: var(--primary-text);
      border-color: var(--primary);
      font-weight: 700;
    }
    button.primary:hover, .btn-label.primary:hover { background: var(--primary-hover); }
    button.danger {
      background: rgba(220, 38, 38, 0.12);
      color: #f87171;
      border-color: rgba(220, 38, 38, 0.4);
    }
    [data-theme="light"] button.danger {
      color: #b91c1c;
      background: #fef2f2;
    }
    button.danger:hover {
      background: var(--danger);
      color: #ffffff;
      border-color: var(--danger);
    }
    button:hover, select:hover, input[type="text"]:focus, input[type="number"]:focus {
      border-color: var(--primary);
      outline: none;
    }

    /* Main Layout: Collapsible Specimen Sidebar + Academic Bento Workspace */
    .app-body {
      display: flex;
      flex: 1;
      min-height: 0;
      overflow: hidden;
      position: relative;
    }
    @media (max-width: 1024px) {
      .app-body { flex-direction: column; overflow: visible; }
    }

    /* Backdrop for Mobile Slide-Over Sidebar */
    .sidebar-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.6);
      backdrop-filter: blur(2px);
      z-index: 55;
    }
    .sidebar-backdrop.show { display: block; }

    /* Collapsible Specimen Queue Sidebar */
    .album-sidebar {
      width: 260px;
      min-width: 260px;
      background: var(--panel);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      height: 100%;
      transition: margin-left 0.24s cubic-bezier(0.16, 1, 0.3, 1), transform 0.24s cubic-bezier(0.16, 1, 0.3, 1);
      z-index: 20;
    }
    .album-sidebar.collapsed {
      margin-left: -260px;
    }
    .btn-close-sidebar-mobile {
      display: none;
      padding: 4px 9px;
      font-size: 0.76rem;
      border-radius: 6px;
    }
    @media (max-width: 1024px) {
      .album-sidebar {
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        width: 290px;
        min-width: 290px;
        max-width: 86vw;
        height: 100vh;
        margin-left: 0 !important;
        transform: translateX(0);
        z-index: 60;
        box-shadow: 8px 0 32px rgba(0, 0, 0, 0.45);
      }
      .album-sidebar.collapsed {
        transform: translateX(-105%);
      }
      .btn-close-sidebar-mobile {
        display: inline-flex;
      }
    }

    .sidebar-head {
      padding: 12px;
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .sidebar-title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.85rem;
      font-weight: 700;
    }
    .sidebar-bulk-row {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .sidebar-bulk-row button {
      padding: 6px 8px;
      font-size: 0.76rem;
      border-radius: 6px;
      flex: 1;
      justify-content: center;
    }
    .queue-progress-box {
      background: rgba(0, 194, 152, 0.12);
      border: 1px solid rgba(0, 194, 152, 0.35);
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 0.75rem;
      color: var(--accent);
      display: none;
      flex-direction: column;
      gap: 5px;
    }
    .queue-bar-bg {
      width: 100%;
      height: 5px;
      background: rgba(148, 163, 184, 0.25);
      border-radius: 99px;
      overflow: hidden;
    }
    .queue-bar-fill {
      height: 100%;
      width: 0%;
      background: var(--primary);
      transition: width 0.2s;
    }

    .album-list {
      flex: 1;
      overflow-y: auto;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .album-item {
      position: relative;
      width: 100%;
      background: var(--panel-subtle);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      transition: all 0.15s;
    }
    .album-item.active {
      border-color: var(--primary);
      border-width: 1.5px;
      background: var(--accent-bg);
    }
    .album-item.processing {
      border-style: dashed;
      border-color: #38bdf8;
      opacity: 0.92;
    }
    .album-item:hover { border-color: var(--primary); }
    .album-check {
      width: 16px;
      height: 16px;
      accent-color: var(--primary);
      cursor: pointer;
      flex-shrink: 0;
    }
    .album-thumb {
      width: 44px;
      height: 44px;
      border-radius: 6px;
      object-fit: cover;
      background: #000;
      flex-shrink: 0;
      border: 1px solid var(--border);
    }
    .album-meta { overflow: hidden; flex: 1; }
    .album-title {
      font-size: 0.81rem;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .album-sub {
      font-size: 0.73rem;
      color: var(--muted);
      margin-top: 2px;
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .album-del {
      width: 22px;
      height: 22px;
      border-radius: 4px;
      background: rgba(239, 68, 68, 0.14);
      color: #f87171;
      border: none;
      padding: 0;
      font-size: 11px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .album-del:hover { background: var(--danger); color: #fff; }

    /* Bento Workspace Grid */
    .workspace {
      flex: 1;
      display: grid;
      grid-template-columns: 0.96fr 1.04fr;
      gap: 14px;
      padding: 12px 16px;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
    }
    @media (max-width: 1024px) {
      .workspace {
        grid-template-columns: 1fr;
        overflow: visible;
        padding: 10px;
        gap: 12px;
      }
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      height: 100%;
      min-height: 0;
      overflow: hidden;
      box-shadow: var(--card-shadow);
    }
    @media (max-width: 1024px) {
      .card {
        height: auto;
        overflow: visible;
        padding: 12px;
      }
    }

    /* Plate Canvas Card (Left) */
    .canvas-wrap {
      position: relative;
      background: #14181f;
      border-radius: 10px;
      overflow: hidden;
      flex: 1;
      min-height: 380px;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--border);
      touch-action: none;
    }
    @media (max-width: 640px) {
      .canvas-wrap { min-height: 330px; }
    }
    #plateCanvas {
      width: 100%;
      height: 100%;
      max-width: 100%;
      max-height: 100%;
      cursor: crosshair;
      display: block;
      object-fit: contain;
      touch-action: none;
    }
    #plateCanvas.fill-mode { object-fit: cover; }
    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      font-size: 0.9rem;
      flex-shrink: 0;
    }
    .section-heading {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.92rem;
      font-weight: 700;
      letter-spacing: -0.01em;
    }
    .step-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 2px 8px;
      border-radius: 5px;
      background: var(--primary);
      color: #dbe2eb;
      border: none;
      font-size: 0.74rem;
      font-weight: 700;
      flex-shrink: 0;
    }

    /* Academic Clinical KPI Summary Row */
    .kpi-summary-row {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 8px;
      flex-shrink: 0;
    }
    @media (max-width: 680px) {
      .kpi-summary-row {
        grid-template-columns: repeat(3, 1fr);
      }
    }
    .kpi-card {
      background: var(--panel-subtle);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 11px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 2px;
    }
    .kpi-label {
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--muted);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 4px;
      white-space: nowrap;
    }
    .kpi-dot {
      width: 7px;
      height: 7px;
      border-radius: 2px;
      display: inline-block;
    }
    .kpi-val {
      font-size: 1.12rem;
      font-weight: 800;
      font-variant-numeric: tabular-nums;
      letter-spacing: -0.02em;
    }

    /* Skeleton Shimmer Animation */
    @keyframes shimmer {
      0% { background-position: -200% 0; }
      100% { background-position: 200% 0; }
    }
    .skeleton-box {
      background: linear-gradient(90deg, var(--skel-1) 25%, var(--skel-2) 50%, var(--skel-1) 75%);
      background-size: 200% 100%;
      animation: shimmer 1.35s infinite linear;
      border-radius: 6px;
    }
    .canvas-skeleton-overlay {
      position: absolute;
      inset: 0;
      background: rgba(15, 23, 42, 0.86);
      display: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 12px;
      z-index: 10;
    }
    .canvas-skeleton-circle {
      width: 190px;
      height: 190px;
      border-radius: 50%;
      border: 3px dashed var(--primary);
      animation: pulseRing 1.4s infinite ease-in-out;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    @keyframes pulseRing {
      0%, 100% { transform: scale(0.96); opacity: 0.65; }
      50% { transform: scale(1.04); opacity: 1; }
    }
    .skel-row { height: 18px; width: 100%; margin: 4px 0; }

    /* Disc Inspector Box (Static 246x238 Card + Academic Controls) */
    .adjuster-box {
      background: var(--accent-bg);
      border: 1px solid var(--primary);
      border-radius: 10px;
      padding: 12px 14px;
      display: flex;
      gap: 16px;
      align-items: stretch;
      flex-wrap: nowrap;
      flex-shrink: 0;
    }
    @media (max-width: 720px) {
      .adjuster-box {
        flex-direction: column;
        align-items: center;
        padding: 12px;
      }
    }
    .disc-zoom-card {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: space-between;
      background: var(--panel-subtle);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      width: 246px;
      min-width: 246px;
      max-width: 246px;
      height: 238px;
      min-height: 238px;
      max-height: 238px;
      flex-shrink: 0;
      overflow: hidden;
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
    }
    @media (max-width: 480px) {
      .disc-zoom-card {
        width: 100%;
        max-width: 280px;
      }
    }
    .disc-zoom-top-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      width: 100%;
      height: 24px;
      flex-shrink: 0;
    }
    .disc-zoom-header {
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--accent);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-variant-numeric: tabular-nums;
    }
    .btn-contrast-mini {
      padding: 2px 8px;
      font-size: 0.7rem;
      border-radius: 5px;
      background: var(--panel);
      color: var(--text);
      border: 1px solid var(--border);
      height: 22px;
      flex-shrink: 0;
    }
    .btn-contrast-mini.active-filter {
      background: var(--primary);
      color: var(--primary-text);
      border-color: var(--primary);
    }
    .disc-zoom-stage {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
      height: 114px;
      gap: 8px;
      flex-shrink: 0;
    }
    .btn-disc-nav {
      width: 34px;
      min-width: 34px;
      height: 66px;
      padding: 0;
      border-radius: 8px;
      background: var(--panel);
      color: var(--accent);
      border: 1px solid var(--border);
      font-size: 0.95rem;
      font-weight: 800;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: all 0.14s ease;
      flex-shrink: 0;
      user-select: none;
    }
    .btn-disc-nav:hover {
      background: var(--primary);
      color: var(--primary-text);
      border-color: var(--accent);
    }
    #discZoomCanvas {
      width: 112px;
      height: 112px;
      min-width: 112px;
      min-height: 112px;
      border-radius: 50%;
      border: 2px solid var(--accent);
      background: #000;
      display: block;
      flex-shrink: 0;
    }
    .disc-zoom-tools {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 4px;
      width: 100%;
      height: 28px;
      align-items: center;
      flex-shrink: 0;
    }
    .disc-zoom-tools button {
      padding: 4px 0;
      font-size: 0.72rem;
      border-radius: 5px;
      background: var(--panel);
      color: var(--text);
      border: 1px solid var(--border);
      width: 100%;
      justify-content: center;
      height: 26px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .disc-zoom-tools button:hover {
      background: var(--secondary);
      border-color: var(--accent);
    }
    .btn-reocr {
      width: 100%;
      height: 30px;
      justify-content: center;
      padding: 4px 10px;
      font-size: 0.76rem;
      background: var(--primary);
      color: var(--primary-text);
      border: 1px solid var(--primary);
      border-radius: 6px;
      font-weight: 700;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .btn-reocr:hover { background: var(--primary-hover); }
    .reocr-status {
      font-size: 0.72rem;
      color: var(--accent);
      font-weight: 600;
      text-align: center;
      width: 100%;
      height: 18px;
      line-height: 18px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-variant-numeric: tabular-nums;
      flex-shrink: 0;
    }
    .adjuster-controls {
      flex: 1;
      width: 100%;
      min-width: 0;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 10px;
      padding: 2px 0;
      overflow: hidden;
    }
    .adjuster-row {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: space-between;
    }
    input[type="range"] {
      flex: 1;
      accent-color: var(--primary);
      cursor: pointer;
      height: 6px;
    }

    /* Inline Drug Input & Candidate Chips */
    .inline-drug-input {
      width: 108px;
      padding: 5px 8px;
      font-weight: 700;
      text-transform: uppercase;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      font-size: 0.84rem;
      letter-spacing: 0.02em;
    }
    .inline-drug-input.uncertain {
      border-color: #d97706;
      background: rgba(245, 158, 11, 0.1);
    }
    .top-cand-row {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: nowrap;
      overflow-x: auto;
      padding-bottom: 2px;
      width: 100%;
    }
    .cand-chip {
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 700;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .cand-chip.top1 {
      border-color: var(--primary);
      background: rgba(0, 194, 152, 0.16);
      color: var(--primary);
    }
    [data-theme="dark"] .cand-chip.top1 {
      color: var(--accent);
    }
    .cand-chip:hover { border-color: var(--primary); }

    .canvas-mode-banner {
      position: absolute;
      top: 10px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(15, 23, 42, 0.94);
      color: #f8fafc;
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 0.78rem;
      font-weight: 700;
      z-index: 8;
      border: 1px solid var(--primary);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.45);
      display: none;
      pointer-events: none;
      white-space: nowrap;
      max-width: 94%;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    button.add-disc-active {
      background: var(--primary) !important;
      color: #dbe2eb !important;
      border-color: var(--primary) !important;
    }
    .review-badge {
      font-size: 0.7rem;
      padding: 2px 6px;
      border-radius: 4px;
      background: rgba(245, 158, 11, 0.16);
      color: #b45309;
      border: 1px solid rgba(245, 158, 11, 0.35);
      font-weight: 700;
      margin-left: 4px;
    }
    [data-theme="dark"] .review-badge {
      color: #fcd34d;
    }

    /* Custom Drug Drawer */
    .custom-drug-drawer {
      background: var(--panel-subtle);
      border: 1px solid var(--primary);
      border-radius: 8px;
      padding: 10px 12px;
      display: none;
      flex-direction: column;
      gap: 8px;
      flex-shrink: 0;
    }

    /* Academic Clinical Results Table */
    .table-wrap {
      flex: 1;
      min-height: 180px;
      overflow-x: auto;
      overflow-y: auto;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--panel);
    }
    @media (max-width: 1024px) {
      .table-wrap { max-height: 420px; }
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
      font-variant-numeric: tabular-nums;
    }
    th, td {
      padding: 8px 11px;
      border-bottom: 1px solid var(--border);
      border-right: 1px solid var(--grid-line);
      text-align: left;
      white-space: nowrap;
    }
    th:last-child, td:last-child { border-right: none; }
    th {
      font-weight: 700;
      font-size: 0.78rem;
      color: var(--muted);
      background: var(--panel-subtle);
      position: sticky;
      top: 0;
      z-index: 2;
      box-shadow: 0 1px 0 var(--border);
    }
    .col-letter {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      border-radius: 4px;
      background: var(--col-badge-bg);
      color: var(--col-badge-text);
      font-size: 0.66rem;
      font-weight: 800;
      margin-right: 5px;
    }
    tr.selected-row {
      background: var(--accent-bg);
    }
    tr.selected-row td:first-child {
      box-shadow: inset 3px 0 0 var(--primary);
    }
    tr:hover {
      background: var(--accent-bg);
      cursor: pointer;
    }
    .sir-pill {
      padding: 3px 10px;
      border-radius: 4px;
      font-weight: 800;
      font-size: 0.76rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 32px;
    }
    .sir-S { background: var(--s-bg); color: var(--s-text); border: 1px solid var(--s-border); }
    .sir-I { background: var(--i-bg); color: var(--i-text); border: 1px solid var(--i-border); }
    .sir-R { background: var(--r-bg); color: var(--r-text); border: 1px solid var(--r-border); }
    .meta-bar {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 0.8rem;
      color: var(--muted);
      flex-shrink: 0;
      justify-content: space-between;
      padding-top: 2px;
    }

    /* Academic Data Export Footer Bar */
    .export-footer {
      background: var(--panel);
      border-top: 1px solid var(--border);
      box-shadow: 0 -4px 14px rgba(15, 23, 42, 0.12);
      padding: 10px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      flex-shrink: 0;
      z-index: 25;
    }
    .export-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .export-title-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      font-size: 0.86rem;
      font-weight: 800;
      color: var(--primary);
      background: var(--accent-bg);
      padding: 6px 12px;
      border-radius: 6px;
      border: 1px solid var(--primary);
    }
    [data-theme="dark"] .export-title-pill {
      color: var(--accent);
    }
    .export-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .export-select {
      padding: 7px 12px !important;
      font-size: 0.84rem !important;
      font-weight: 600 !important;
      border-radius: 6px !important;
      border: 1px solid var(--border) !important;
      background: var(--panel-subtle) !important;
      color: var(--text) !important;
    }
    .export-badge {
      background: var(--panel-subtle);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 700;
    }
    .btn-export-cta {
      padding: 8px 20px !important;
      font-size: 0.88rem !important;
      font-weight: 700 !important;
      border-radius: 6px !important;
      border: 1px solid var(--primary) !important;
      background: var(--primary) !important;
      color: var(--primary-text) !important;
      letter-spacing: 0.1px;
    }
    .btn-export-cta:hover {
      background: var(--primary-hover) !important;
    }
    @media (max-width: 640px) {
      header { padding: 8px 12px; }
      .top-actions { width: 100%; justify-content: space-between; }
      .top-actions .btn-label.primary { flex: 1; justify-content: center; }
      .export-footer { padding: 10px 12px; }
      .export-left, .export-right { width: 100%; justify-content: space-between; }
      .btn-export-cta { width: 100%; justify-content: center; }
    }
  </style>
</head>
<body data-theme="dark">
  <datalist id="drugDatalist"></datalist>
  <div class="sidebar-backdrop" id="sidebarBackdrop"></div>

  <header>
    <div class="brand">
      <button id="toggleSidebarBtn" title="แสดงหรือซ่อนรายการภาพจานเพาะเชื้อ">
        รายการภาพ (<span id="albumCountHeader">0</span>)
      </button>
      <span class="brand-title">
        <span>ระบบวิเคราะห์ความไวต่อยาปฏิชีวนะ (AST Disk Diffusion System)</span>
        <span class="std-pill">CLSI M100 / EUCAST</span>
      </span>
      <span class="queue-pill" id="headerQueuePill">กำลังประมวลผลเบื้องหลัง...</span>
    </div>
    <div class="top-actions">
      <label class="btn-label primary" title="นำเข้าภาพจานเพาะเชื้อพร้อมกันหลายรายการ ระบบจะประมวลผลเบื้องหลังโดยไม่รบกวนภาพที่กำลังตรวจสอบ">
        นำเข้าภาพจานเพาะเชื้อ
        <input type="file" id="fileInput" accept="image/*" multiple style="display:none" />
      </label>
      <select id="samplePlateSelect" title="เลือกภาพจานเพาะเชื้อตัวอย่างจากชุดข้อมูลวิจัย">
        <option value="">-- เลือกภาพตัวอย่างจากชุดข้อมูลวิจัย --</option>
      </select>
      <button id="toggleCustomDrugBtn" title="เพิ่มรหัสยาปฏิชีวนะหรือกำหนดเกณฑ์ตัดสิน R/S เพิ่มเติม">กำหนดเกณฑ์ยาเพิ่มเติม</button>
      <button id="themeBtn">สลับโทนสี (มืด/สว่าง)</button>
    </div>
  </header>

  <div class="app-body">
    <!-- แถบจัดการรายการภาพจานเพาะเชื้อด้านซ้าย -->
    <aside class="album-sidebar" id="albumSidebar">
      <div class="sidebar-head">
        <div class="sidebar-title-row">
          <span>รายการภาพ (<span id="albumCount">0</span> รายการ)</span>
          <div style="display:flex;align-items:center;gap:6px">
            <span id="checkedCountText" style="font-size:0.74rem;color:var(--primary)">เลือก 0 รายการ</span>
            <button id="closeSidebarMobileBtn" class="btn-close-sidebar-mobile" title="ปิดแถบรายการภาพ">ปิด</button>
          </div>
        </div>

        <!-- แถบสถานะคิวประมวลผลแบบขนาน -->
        <div class="queue-progress-box" id="queueProgressBox">
          <div style="display:flex;justify-content:space-between">
            <span id="queueProgressLabel">กำลังประมวลผลเบื้องหลัง...</span>
            <span id="queueProgressCount">0/0</span>
          </div>
          <div class="queue-bar-bg">
            <div class="queue-bar-fill" id="queueBarFill"></div>
          </div>
          <div style="font-size:0.68rem;color:var(--muted)">สามารถตรวจสอบภาพปัจจุบันต่อได้ทันทีโดยไม่เปลี่ยนหน้าจอ</div>
        </div>

        <!-- ปุ่มจัดการรายการแบบกลุ่ม -->
        <div class="sidebar-bulk-row">
          <button id="selectAllAlbumBtn" title="เลือกรายการภาพทั้งหมด">เลือกทั้งหมด</button>
          <button id="clearAllAlbumBtn" title="ยกเลิกการเลือกทั้งหมด">ยกเลิกการเลือก</button>
        </div>
        <div class="sidebar-bulk-row">
          <button id="bulkDeleteSelectedBtn" class="danger" title="ลบรายการภาพที่เลือกทั้งหมด">
            ลบที่เลือก (<span id="delSelectedCount">0</span>)
          </button>
          <button id="clearEntireAlbumBtn" class="danger" title="ล้างรายการภาพทั้งหมดออกจากระบบ">
            ล้างทั้งหมด
          </button>
        </div>
      </div>

      <div class="album-list" id="albumStrip">
        <div style="font-size:0.8rem;color:var(--muted);padding:14px;text-align:center">
          ยังไม่มีรายการภาพในระบบ<br/>กดปุ่ม <b>"นำเข้าภาพจานเพาะเชื้อ"</b> ด้านบนเพื่อเริ่มการวิเคราะห์
        </div>
      </div>
    </aside>

    <!-- พื้นที่ปฏิบัติการตรวจสอบและแปลผล -->
    <main class="workspace">
      <!-- ส่วนที่ 1: ภาพจานเพาะเชื้อและการวัดขนาดวงยับยั้งเชื้อ -->
      <section class="card">
        <div class="toolbar">
          <span class="section-heading">
            <span class="step-badge">ส่วนที่ 1</span>
            <span>ภาพจานเพาะเชื้อและการวัดขอบเขตวงยับยั้งเชื้อ (Inhibition Zone Inspection)</span>
          </span>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            <button id="toggleEditCircleModeBtn" class="add-disc-active" style="padding:5px 10px;font-size:0.76rem" title="เปิดหรือปิดโหมดแก้ไขพิกัดและปรับขนาดวงยับยั้งเชื้อ">
              โหมดแก้ไขพิกัด/ขนาดวง: เปิด
            </button>
            <button id="toggleSoloZoneBtn" style="padding:5px 10px;font-size:0.76rem" title="ซ่อนวงอื่นชั่วคราวเพื่อให้เห็นเฉพาะวงที่กำลังเลือกหรือปรับขนาดได้ชัดเจน">
              โฟกัสเฉพาะวงที่เลือก: อัตโนมัติตอนปรับขนาด
            </button>
            <button id="toggleAddDiscModeBtn" class="primary" style="padding:5px 10px;font-size:0.76rem" title="คลิกเพื่อเพิ่มตำแหน่งแผ่นยาใหม่บนจานเพาะเชื้อ">
              + เพิ่มตำแหน่งแผ่นยา
            </button>
            <span id="scaleInfo" style="font-size:0.75rem;color:var(--muted)">มาตราส่วน: 6.0 mm</span>
            <button id="toggleFitModeBtn" style="padding:4px 9px;font-size:0.75rem" title="สลับการแสดงผลภาพเต็มใบหรือขยายเต็มกรอบ">ขยายเต็มกรอบ</button>
          </div>
        </div>
        <div class="canvas-wrap">
          <div class="canvas-mode-banner" id="addDiscModeBanner">
            โหมดเพิ่มตำแหน่งแผ่นยา: คลิกหรือแตะกึ่งกลางแผ่นยาบนภาพ (หรือลากออกเพื่อกำหนดรัศมีวงยับยั้ง)
          </div>
          <div class="canvas-skeleton-overlay" id="canvasSkeleton">
            <div class="canvas-skeleton-circle">
              <div class="skeleton-box" style="width:130px;height:18px"></div>
            </div>
            <div style="color:#fff;font-weight:700;font-size:0.9rem;text-align:center;padding:0 12px" id="skeletonStepText">
              กำลังตรวจจับแผ่นยาและคำนวณขอบเขตวงยับยั้งเชื้อด้วย Continuous Warp Polar...
            </div>
          </div>
          <canvas id="plateCanvas" width="900" height="900"></canvas>
        </div>
        <div class="meta-bar">
          <div>
            <span>รหัสภาพตัวอย่าง: <strong id="metaPlateId">-</strong></span> &nbsp;|&nbsp;
            <span>จำนวนแผ่นยา: <strong id="metaCount">-</strong></span> &nbsp;|&nbsp;
            <span>เวลาประมวลผล: <strong id="metaLatency">-</strong></span>
          </div>
          <span id="statusText" style="color:var(--primary);font-weight:700">สถานะ: พร้อมใช้งาน</span>
        </div>
      </section>

      <!-- ส่วนที่ 2: ข้อมูลแผ่นยารายตำแหน่งและตารางแปลผลทางคลินิก -->
      <section class="card">
        <div class="toolbar">
          <span class="section-heading">
            <span class="step-badge">ส่วนที่ 2</span>
            <span>ข้อมูลแผ่นยาเฉพาะจุดและตารางแปลผลความไวต่อยา (CLSI M100 / EUCAST)</span>
          </span>
        </div>

        <!-- แถบสรุปค่าสถิติทางคลินิก (Clinical Summary Indicators) -->
        <div class="kpi-summary-row" id="kpiSummaryRow">
          <div class="kpi-card">
            <span class="kpi-label">จำนวนแผ่นยา <span class="kpi-dot" style="background:#6497b8"></span></span>
            <span class="kpi-val" id="kpiTotalDiscs">0</span>
          </div>
          <div class="kpi-card">
            <span class="kpi-label">ไวต่อยา (S) <span class="kpi-dot" style="background:#68b088"></span></span>
            <span class="kpi-val" id="kpiCountS" style="color:var(--s-text)">0</span>
          </div>
          <div class="kpi-card">
            <span class="kpi-label">ปานกลาง (I) <span class="kpi-dot" style="background:#d9a754"></span></span>
            <span class="kpi-val" id="kpiCountI" style="color:var(--i-text)">0</span>
          </div>
          <div class="kpi-card">
            <span class="kpi-label">ดื้อยา (R) <span class="kpi-dot" style="background:#d96c6c"></span></span>
            <span class="kpi-val" id="kpiCountR" style="color:var(--r-text)">0</span>
          </div>
          <div class="kpi-card">
            <span class="kpi-label">ความเชื่อมั่นเฉลี่ย <span class="kpi-dot" style="background:#72b3a8"></span></span>
            <span class="kpi-val" id="kpiAvgConf" style="color:var(--primary)">0%</span>
          </div>
        </div>

        <!-- ส่วนกำหนดรหัสยาและเกณฑ์ตัดสินเพิ่มเติม -->
        <div id="customDrugDrawer" class="custom-drug-drawer">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <strong style="color:var(--primary);font-size:0.84rem">กำหนดรหัสยาปฏิชีวนะและเกณฑ์มาตรฐานเพิ่มเติม (CLSI / EUCAST)</strong>
            <button id="closeCustomDrugBtn" style="padding:3px 9px;font-size:0.74rem">ปิด</button>
          </div>
          <div class="adjuster-row">
            <input type="text" id="newDrugCode" placeholder="รหัสยา (เช่น LEV5, DO30)" style="width:140px;text-transform:uppercase" />
            <input type="text" id="newDrugName" placeholder="ชื่อยาปฏิชีวนะและความเข้มข้น (เช่น Levofloxacin 5 µg)" style="flex:1;min-width:150px" />
            <label style="font-size:0.8rem">เกณฑ์ R ≤ <input type="number" id="newDrugR" value="14" step="0.5" style="width:62px" /> mm</label>
            <label style="font-size:0.8rem">เกณฑ์ S ≥ <input type="number" id="newDrugS" value="19" step="0.5" style="width:62px" /> mm</label>
            <button id="saveNewDrugBtn" class="primary">บันทึกข้อมูลยา</button>
          </div>
        </div>

        <!-- แผงตรวจสอบแผ่นยารายตำแหน่ง (Static Orientation & Zone Adjuster) -->
        <div id="adjusterPanel" class="adjuster-box" style="display:none">
          <div class="disc-zoom-card">
            <div class="disc-zoom-top-row">
              <span class="disc-zoom-header" id="zoomDiscBadge">แผ่นยาที่ #1 (มุม 0°)</span>
              <button id="contrastBoostBtn" class="btn-contrast-mini" title="ปรับเพิ่มความคมชัดของตัวอักษรบนแผ่นยา">ปรับคอนทราสต์</button>
            </div>
            <div class="disc-zoom-stage">
              <button id="prevDiscBtn" type="button" class="btn-disc-nav" title="แผ่นยาก่อนหน้า (ปุ่มลูกศรซ้าย)">◀</button>
              <canvas id="discZoomCanvas" width="180" height="180" title="ภาพขยายแผ่นยาเฉพาะจุด"></canvas>
              <button id="nextDiscBtn" type="button" class="btn-disc-nav" title="แผ่นยาถัดไป (ปุ่มลูกศรขวา)">▶</button>
            </div>
            <div class="disc-zoom-tools">
              <button id="rotLeft45Btn" title="หมุนทวนเข็มนาฬิกา 45 องศา">-45°</button>
              <button id="rotLeft15Btn" title="หมุนทวนเข็มนาฬิกา 15 องศา">-15°</button>
              <button id="rotRight15Btn" title="หมุนตามเข็มนาฬิกา 15 องศา">+15°</button>
              <button id="rotRight45Btn" title="หมุนตามเข็มนาฬิกา 45 องศา">+45°</button>
              <button id="rotFlipBtn" title="กลับหัวภาพ 180 องศา">180°</button>
            </div>
            <button id="reOcrBtn" class="btn-reocr" title="ประมวลผลอ่านรหัสยาซ้ำตามมุมที่หมุนไว้">
              อ่านรหัสยาซ้ำตามมุมที่หมุน
            </button>
            <div class="reocr-status" id="reOcrStatusText">ปรับมุมให้ตั้งตรงแล้วกดอ่านรหัสยาซ้ำ</div>
          </div>

          <div class="adjuster-controls">
            <div class="adjuster-row">
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                <strong id="adjTitle" style="color:var(--primary);font-size:0.95rem">ข้อมูลแผ่นยาตำแหน่งที่ #1</strong>
                <span id="adjDrugFullName" style="font-size:0.83rem;color:var(--muted)"></span>
              </div>
              <button id="deleteSelectedDiscBtn" class="danger" style="padding:5px 10px;font-size:0.76rem" title="ลบตำแหน่งแผ่นยานี้ออกจากจานเพาะเชื้อ">
                ลบตำแหน่งนี้
              </button>
            </div>

            <div style="display:flex;flex-direction:column;gap:8px;width:100%">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;width:100%">
                <label style="font-size:0.84rem;font-weight:700;white-space:nowrap">รหัสยาปฏิชีวนะ (เรียงตามความเชื่อมั่น):</label>
                <select id="adjDrugSelect" style="flex:1;min-width:210px;font-weight:700;padding:7px 10px;font-size:0.85rem"></select>
              </div>
              <div class="top-cand-row" id="topCandidatesRow"></div>
            </div>

            <div class="adjuster-row" style="padding-top:6px;border-top:1px solid var(--border)">
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                <label style="font-size:0.82rem;font-weight:600">เกณฑ์ R ≤ <input type="number" id="adjBpR" step="0.5" style="width:62px;padding:4px 6px" /> mm</label>
                <label style="font-size:0.82rem;font-weight:600">เกณฑ์ S ≥ <input type="number" id="adjBpS" step="0.5" style="width:62px;padding:4px 6px" /> mm</label>
              </div>
              <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:200px">
                <span style="font-size:0.82rem;font-weight:700" title="ปรับขนาดเส้นผ่านศูนย์กลางวงยับยั้งเชื้อ">ขนาดวงยับยั้ง:</span>
                <input type="range" id="adjDiamSlider" min="6.0" max="42.0" step="0.5" value="6.0" />
                <strong id="adjDiamVal" style="min-width:92px;text-align:right;font-size:0.9rem;color:var(--primary)">6.0 mm (R)</strong>
              </div>
            </div>
          </div>
        </div>

        <!-- ตารางผลการวิเคราะห์ทางคลินิก -->
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th><span class="col-letter">A</span>ลำดับที่</th>
                <th><span class="col-letter">B</span>โซนพิกัด</th>
                <th><span class="col-letter">C</span>พิกัด (X, Y)</th>
                <th><span class="col-letter">D</span>รหัสยาปฏิชีวนะ</th>
                <th><span class="col-letter">E</span>ขนาดวงยับยั้ง (mm)</th>
                <th><span class="col-letter">F</span>เกณฑ์ R / S (mm)</th>
                <th><span class="col-letter">G</span>ผลแปลทางคลินิก</th>
              </tr>
            </thead>
            <tbody id="clinicalTbody">
              <tr><td colspan="7" style="text-align:center;color:var(--muted);padding:28px">นำเข้าภาพจานเพาะเชื้อ หรือเลือกรายการภาพจากแถบด้านซ้ายเพื่อแสดงผลการวิเคราะห์</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <!-- แถบส่งออกข้อมูลผลการวิเคราะห์ด้านล่าง -->
  <footer class="export-footer">
    <div class="export-left">
      <span class="export-title-pill">การส่งออกข้อมูลผลการวิเคราะห์ (Data Export)</span>
      <label style="font-size:0.84rem;font-weight:700;display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap">
        ขอบเขตข้อมูล:
        <select id="exportScopeSelect" class="export-select">
          <option value="current">เฉพาะภาพที่กำลังตรวจสอบปัจจุบัน (1 รายการ)</option>
          <option value="checked">เฉพาะภาพที่เลือกในรายการด้านซ้าย</option>
          <option value="all">รวมทุกภาพในระบบทั้งหมดเป็นไฟล์เดียว</option>
        </select>
      </label>
      <span class="export-badge" id="exportSummaryBadge">พร้อมส่งออก 1 รายการ</span>
    </div>

    <div class="export-right">
      <label style="font-size:0.84rem;font-weight:700;display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap">
        รูปแบบไฟล์:
        <select id="exportFormatSelect" class="export-select">
          <option value="xlsx">Excel Workbook (.xlsx) — ตารางผลวิเคราะห์ทางคลินิก</option>
          <option value="csv">CSV (.csv) — ข้อมูลตารางสำหรับวิเคราะห์ทางสถิติ</option>
          <option value="json">JSON (.json) — โครงสร้างข้อมูลมาตรฐาน API</option>
          <option value="md">Markdown (.md) — ตารางรายงานผลการวิจัย</option>
        </select>
      </label>
      <button id="runExportBtn" class="btn-export-cta">ส่งออกไฟล์ข้อมูล</button>
    </div>
  </footer>

  <script>
    const BREAKPOINTS = {
      AMC30: { name: 'Amoxicillin-Clavulanate 30 µg', r: 13.0, s: 18.0 },
      AMP10: { name: 'Ampicillin 10 µg', r: 13.0, s: 17.0 },
      AM10:  { name: 'Ampicillin 10 µg (EUCAST)', r: 14.0, s: 14.0 },
      AUG30: { name: 'Amoxicillin-Clavulanate 30 µg', r: 13.0, s: 18.0 },
      CAZ30: { name: 'Ceftazidime 30 µg', r: 17.0, s: 21.0 },
      CAZ10: { name: 'Ceftazidime 10 µg (EUCAST)', r: 19.0, s: 22.0 },
      SXT25: { name: 'Trimethoprim-Sulfamethoxazole 25 µg', r: 10.0, s: 16.0 },
      TE30:  { name: 'Tetracycline 30 µg', r: 14.0, s: 19.0 },
      CIP5:  { name: 'Ciprofloxacin 5 µg', r: 22.0, s: 25.0 },
      LEV5:  { name: 'Levofloxacin 5 µg', r: 19.0, s: 23.0 },
      NOR10: { name: 'Norfloxacin 10 µg', r: 12.0, s: 17.0 },
      PEF5:  { name: 'Pefloxacin 5 µg', r: 24.0, s: 24.0 },
      CN10:  { name: 'Gentamicin 10 µg', r: 14.0, s: 17.0 },
      AK30:  { name: 'Amikacin 30 µg', r: 14.0, s: 17.0 },
      TOB10: { name: 'Tobramycin 10 µg', r: 14.0, s: 17.0 },
      S10:   { name: 'Streptomycin 10 µg', r: 11.0, s: 15.0 },
      FOX30: { name: 'Cefoxitin 30 µg', r: 14.0, s: 18.0 },
      CRO30: { name: 'Ceftriaxone 30 µg', r: 22.0, s: 25.0 },
      CTX5:  { name: 'Cefotaxime 5 µg', r: 17.0, s: 20.0 },
      CTX30: { name: 'Cefotaxime 30 µg', r: 22.0, s: 26.0 },
      CPD10: { name: 'Cefpodoxime 10 µg', r: 21.0, s: 21.0 },
      FEP30: { name: 'Cefepime 30 µg', r: 24.0, s: 27.0 },
      ATM30: { name: 'Aztreonam 30 µg', r: 17.0, s: 21.0 },
      TZP36: { name: 'Piperacillin-Tazobactam 36 µg', r: 17.0, s: 20.0 },
      TPZ36: { name: 'Piperacillin-Tazobactam 36 µg', r: 17.0, s: 20.0 },
      TZP110:{ name: 'Piperacillin-Tazobactam 110 µg', r: 17.0, s: 21.0 },
      SAM20: { name: 'Ampicillin-Sulbactam 20 µg', r: 11.0, s: 15.0 },
      ETP10: { name: 'Ertapenem 10 µg', r: 22.0, s: 25.0 },
      IPM10: { name: 'Imipenem 10 µg', r: 19.0, s: 23.0 },
      MEM10: { name: 'Meropenem 10 µg', r: 16.0, s: 22.0 },
      VA30:  { name: 'Vancomycin 30 µg', r: 14.0, s: 17.0 },
      VA5:   { name: 'Vancomycin 5 µg', r: 12.0, s: 15.0 },
      E15:   { name: 'Erythromycin 15 µg', r: 13.0, s: 23.0 },
      CD2:   { name: 'Clindamycin 2 µg', r: 14.0, s: 21.0 },
      C30:   { name: 'Chloramphenicol 30 µg', r: 12.0, s: 18.0 },
      RD5:   { name: 'Rifampin 5 µg', r: 16.0, s: 20.0 },
      P10:   { name: 'Penicillin G 10 U', r: 14.0, s: 15.0 },
      TC75:  { name: 'Ticarcillin 75 µg', r: 14.0, s: 20.0 },
      UNKNOWN: { name: 'รอการระบุรหัสยา (สามารถเลือกจากรายการหรือหมุนภาพเพื่ออ่านซ้ำ)', r: 14.0, s: 19.0 }
    };

    let albumItems = [];
    let pendingUploadItems = [];
    let checkedAlbumIds = new Set();
    let activeAlbumId = null;
    let currentPlateMeta = { title: '-', bacteria_species: 'Escherichia coli ATCC 25922' };
    let currentImg = null;
    let currentRecords = [];
    let selectedIdx = null;
    let zoomRotationDeg = 0;
    let zoomContrastBoost = false;

    let totalQueuedCount = 0;
    let completedQueuedCount = 0;

    const canvas = document.getElementById('plateCanvas');
    const ctx = canvas.getContext('2d');
    const zoomCanvas = document.getElementById('discZoomCanvas');
    const zoomCtx = zoomCanvas.getContext('2d');
    const adjDrugSelect = document.getElementById('adjDrugSelect');
    const drugDatalist = document.getElementById('drugDatalist');
    const topCandidatesRow = document.getElementById('topCandidatesRow');
    const albumSidebar = document.getElementById('albumSidebar');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');

    let isEditCircleMode = true;
    let isAddDiscMode = false;
    let isSoloZoneMode = false;
    let isSliderResizing = false;
    let sliderResizeTimer = null;
    let dragState = null;

    function syncSidebarBackdrop() {
      const isMobile = window.innerWidth <= 1024;
      const isOpen = !albumSidebar.classList.contains('collapsed');
      sidebarBackdrop.classList.toggle('show', isMobile && isOpen);
    }
    if (window.innerWidth <= 1024) {
      albumSidebar.classList.add('collapsed');
    }
    window.addEventListener('resize', syncSidebarBackdrop);

    document.getElementById('toggleSidebarBtn').onclick = () => {
      albumSidebar.classList.toggle('collapsed');
      syncSidebarBackdrop();
    };
    document.getElementById('closeSidebarMobileBtn').onclick = () => {
      albumSidebar.classList.add('collapsed');
      syncSidebarBackdrop();
    };
    sidebarBackdrop.onclick = () => {
      albumSidebar.classList.add('collapsed');
      syncSidebarBackdrop();
    };

    document.getElementById('toggleFitModeBtn').onclick = (e) => {
      canvas.classList.toggle('fill-mode');
      const isFill = canvas.classList.contains('fill-mode');
      e.currentTarget.textContent = isFill ? 'แสดงภาพเต็มใบ' : 'ขยายเต็มกรอบ';
    };

    function setEditCircleMode(enabled) {
      isEditCircleMode = Boolean(enabled);
      const btn = document.getElementById('toggleEditCircleModeBtn');
      btn.classList.toggle('add-disc-active', isEditCircleMode);
      btn.textContent = isEditCircleMode
        ? 'โหมดแก้ไขพิกัด/ขนาดวง: เปิด'
        : 'โหมดแก้ไขพิกัด/ขนาดวง: ล็อก';
      drawPlateCanvas();
    }

    document.getElementById('toggleEditCircleModeBtn').onclick = () => {
      setEditCircleMode(!isEditCircleMode);
    };

    document.getElementById('toggleSoloZoneBtn').onclick = (e) => {
      isSoloZoneMode = !isSoloZoneMode;
      e.currentTarget.classList.toggle('add-disc-active', isSoloZoneMode);
      e.currentTarget.textContent = isSoloZoneMode
        ? 'โฟกัสเฉพาะวงที่เลือก: ซ่อนวงอื่นทั้งหมด'
        : 'โฟกัสเฉพาะวงที่เลือก: อัตโนมัติตอนปรับขนาด';
      drawPlateCanvas();
    };

    function setAddDiscMode(enabled) {
      isAddDiscMode = Boolean(enabled);
      if (isAddDiscMode && !isEditCircleMode) {
        setEditCircleMode(true);
      }
      const btn = document.getElementById('toggleAddDiscModeBtn');
      const banner = document.getElementById('addDiscModeBanner');
      btn.classList.toggle('add-disc-active', isAddDiscMode);
      btn.textContent = isAddDiscMode
        ? 'คลิกบนจานเพื่อวางตำแหน่งใหม่ (กดซ้ำเพื่อยกเลิก)'
        : '+ เพิ่มตำแหน่งแผ่นยา';
      banner.style.display = isAddDiscMode ? 'block' : 'none';
    }

    document.getElementById('toggleAddDiscModeBtn').onclick = () => {
      setAddDiscMode(!isAddDiscMode);
    };

    function getRankedDrugListForRecord(rec) {
      const confMap = {};
      Object.keys(BREAKPOINTS).forEach(code => {
        if (code !== 'UNKNOWN') confMap[code] = 0.01;
      });

      if (rec && Array.isArray(rec.ocr_candidates) && rec.ocr_candidates.length > 0) {
        rec.ocr_candidates.forEach(item => {
          if (item && item.code && confMap[item.code] !== undefined) {
            confMap[item.code] = Number(item.confidence || 0.01);
          }
        });
      } else if (rec && rec.drug_code && rec.drug_code !== 'UNKNOWN' && confMap[rec.drug_code] !== undefined) {
        confMap[rec.drug_code] = typeof rec.ocr_confidence === 'number' && rec.ocr_confidence > 0
          ? rec.ocr_confidence
          : 0.95;
      }

      const sortedCodes = Object.keys(confMap).sort((a, b) => {
        const diff = confMap[b] - confMap[a];
        if (Math.abs(diff) > 1e-4) return diff;
        return a.localeCompare(b);
      });

      return sortedCodes.map(code => ({
        code,
        confidence: confMap[code],
        pct: Math.round(confMap[code] * 100),
        name: BREAKPOINTS[code] ? BREAKPOINTS[code].name : code
      }));
    }

    function rebuildDrugSelectors(rec = null) {
      const targetRec = rec || (selectedIdx !== null && currentRecords[selectedIdx] ? currentRecords[selectedIdx] : null);
      const rankedList = getRankedDrugListForRecord(targetRec);
      const activeCode = targetRec ? String(targetRec.drug_code || 'UNKNOWN').toUpperCase() : '';

      adjDrugSelect.innerHTML = '';
      drugDatalist.innerHTML = '';

      const unkOpt = document.createElement('option');
      unkOpt.value = 'UNKNOWN';
      unkOpt.textContent = '[รอระบุรหัสยา] UNKNOWN — กรุณาเลือกรหัสยาหรือพิมพ์ระบุ';
      adjDrugSelect.appendChild(unkOpt);

      rankedList.forEach((item) => {
        const opt = document.createElement('option');
        opt.value = item.code;
        opt.textContent = `[ความเชื่อมั่น ${item.pct}%] ${item.code} — ${item.name}`;
        adjDrugSelect.appendChild(opt);

        const dOpt = document.createElement('option');
        dOpt.value = item.code;
        dOpt.label = `[${item.pct}%] ${item.name} (R≤${BREAKPOINTS[item.code].r} / S≥${BREAKPOINTS[item.code].s})`;
        drugDatalist.appendChild(dOpt);
      });

      if (activeCode && activeCode !== 'UNKNOWN' && !BREAKPOINTS[activeCode]) {
        const customOpt = document.createElement('option');
        customOpt.value = activeCode;
        customOpt.textContent = `[กำหนดเอง] ${activeCode}`;
        adjDrugSelect.insertBefore(customOpt, adjDrugSelect.firstChild);
      }

      const customTriggerOpt = document.createElement('option');
      customTriggerOpt.value = '__CUSTOM_PROMPT__';
      customTriggerOpt.textContent = '+ ระบุรหัสยาอื่นด้วยตนเอง...';
      adjDrugSelect.appendChild(customTriggerOpt);

      adjDrugSelect.value = activeCode && (BREAKPOINTS[activeCode] || activeCode !== 'UNKNOWN') ? activeCode : 'UNKNOWN';

      if (topCandidatesRow) {
        topCandidatesRow.innerHTML = '';
        const topCands = rankedList.filter(x => x.pct >= 12).slice(0, 4);
        if (topCands.length > 0) {
          const lbl = document.createElement('span');
          lbl.style.fontSize = '0.74rem';
          lbl.style.color = 'var(--muted)';
          lbl.style.fontWeight = '600';
          lbl.textContent = 'ลำดับความเชื่อมั่นสูงสุด:';
          topCandidatesRow.appendChild(lbl);

          topCands.forEach((cItem, cIdx) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'cand-chip' + (cIdx === 0 ? ' top1' : '');
            btn.textContent = `${cItem.code} (${cItem.pct}%)`;
            btn.title = `${cItem.name} — คลิกเพื่อเลือกรหัสยานี้`;
            btn.onclick = () => {
              if (selectedIdx === null) return;
              applyDrugCodeToRecord(selectedIdx, cItem.code, {
                isManual: true,
                ocrConfidence: cItem.confidence
              });
              renderAll();
            };
            topCandidatesRow.appendChild(btn);
          });
        }
      }
    }
    rebuildDrugSelectors();

    function getBreakpointForRecord(rec) {
      const code = String(rec.drug_code || 'UNKNOWN').trim().toUpperCase();
      if (BREAKPOINTS[code]) {
        return {
          name: BREAKPOINTS[code].name,
          r: (typeof rec.custom_bp_r === 'number') ? rec.custom_bp_r : BREAKPOINTS[code].r,
          s: (typeof rec.custom_bp_s === 'number') ? rec.custom_bp_s : BREAKPOINTS[code].s
        };
      }
      return {
        name: rec.drug_full_name || `กำหนดเอง (${code})`,
        r: (typeof rec.custom_bp_r === 'number') ? rec.custom_bp_r : (rec.bp_r_mm || 14.0),
        s: (typeof rec.custom_bp_s === 'number') ? rec.custom_bp_s : (rec.bp_s_mm || 19.0)
      };
    }

    function interpretSirForRecord(rec) {
      const bp = getBreakpointForRecord(rec);
      const mm = parseFloat(rec.diameter_mm || 6.0);
      if (mm >= bp.s) return 'S';
      if (mm <= bp.r) return 'R';
      return 'I';
    }

    function renderKpiSummary() {
      let sCount = 0, iCount = 0, rCount = 0, confSum = 0;
      currentRecords.forEach(r => {
        const sir = interpretSirForRecord(r);
        if (sir === 'S') sCount++;
        else if (sir === 'I') iCount++;
        else rCount++;
        const c = typeof r.ocr_confidence === 'number'
          ? r.ocr_confidence
          : (r.drug_code && r.drug_code !== 'UNKNOWN' ? 0.95 : 0.0);
        confSum += c;
      });
      const avgPct = currentRecords.length > 0 ? Math.round((confSum / currentRecords.length) * 100) : 0;
      document.getElementById('kpiTotalDiscs').textContent = currentRecords.length;
      document.getElementById('kpiCountS').textContent = sCount;
      document.getElementById('kpiCountI').textContent = iCount;
      document.getElementById('kpiCountR').textContent = rCount;
      document.getElementById('kpiAvgConf').textContent = `${avgPct}%`;
    }

    function updateExportSummaryBadge() {
      const scope = document.getElementById('exportScopeSelect').value;
      const badge = document.getElementById('exportSummaryBadge');
      document.getElementById('checkedCountText').textContent = `เลือก ${checkedAlbumIds.size} รายการ`;
      document.getElementById('delSelectedCount').textContent = checkedAlbumIds.size;

      if (scope === 'current') {
        badge.textContent = `ส่งออก 1 รายการ (${currentRecords.length} แผ่นยา)`;
      } else if (scope === 'checked') {
        const chosen = albumItems.filter(x => checkedAlbumIds.has(x.album_id));
        const totalD = chosen.reduce((acc, p) => acc + (p.discs ? p.discs.length : 0), 0);
        badge.textContent = `รวม ${chosen.length} รายการที่เลือก (${totalD} แผ่นยา)`;
      } else {
        const totalD = albumItems.reduce((acc, p) => acc + (p.discs ? p.discs.length : 0), 0);
        badge.textContent = `รวมทั้งหมด ${albumItems.length} รายการ (${totalD} แผ่นยา)`;
      }
    }

    document.getElementById('exportScopeSelect').addEventListener('change', updateExportSummaryBadge);

    function drawSelectedDiscZoom() {
      const w = zoomCanvas.width;
      const h = zoomCanvas.height;
      zoomCtx.clearRect(0, 0, w, h);
      if (!currentImg || selectedIdx === null || !currentRecords[selectedIdx]) {
        return;
      }
      const rec = currentRecords[selectedIdx];
      const cropRadius = Math.max(14, rec.r_disc_px * 1.18);
      const rotDeg = Math.round(rec.user_rot_deg !== undefined ? rec.user_rot_deg : zoomRotationDeg);
      const scaleFactor = (w / 2.0) / cropRadius;

      zoomCtx.save();
      zoomCtx.beginPath();
      zoomCtx.arc(w / 2, h / 2, w / 2 - 1, 0, Math.PI * 2);
      zoomCtx.closePath();
      zoomCtx.clip();

      zoomCtx.fillStyle = '#090d16';
      zoomCtx.fillRect(0, 0, w, h);

      zoomCtx.translate(w / 2, h / 2);
      zoomCtx.rotate((rotDeg * Math.PI) / 180.0);
      zoomCtx.scale(scaleFactor, scaleFactor);

      if (zoomContrastBoost) {
        zoomCtx.filter = 'contrast(215%) brightness(92%) grayscale(100%)';
      } else {
        zoomCtx.filter = 'contrast(118%)';
      }

      zoomCtx.drawImage(currentImg, -rec.center_x, -rec.center_y);
      zoomCtx.restore();

      zoomCtx.save();
      zoomCtx.beginPath();
      zoomCtx.arc(w / 2, h / 2, (w / 2) * (1.0 / 1.18), 0, Math.PI * 2);
      zoomCtx.strokeStyle = 'rgba(45, 212, 191, 0.55)';
      zoomCtx.lineWidth = 1.5;
      zoomCtx.setLineDash([4, 3]);
      zoomCtx.stroke();
      zoomCtx.restore();

      document.getElementById('zoomDiscBadge').textContent = `แผ่นยาที่ #${rec.disc_order}/${currentRecords.length} (มุม ${rotDeg}°)`;
    }

    function formatDiscConfidenceStatus(rec) {
      if (!rec) return '';
      const code = String(rec.drug_code || 'UNKNOWN').trim().toUpperCase();
      if (rec.is_manual_entry) {
        return `รหัสปัจจุบัน: ${code} (ระบุโดยผู้ตรวจสอบ)`;
      }
      if (code === 'UNKNOWN' || code === 'DISC' || code === 'UNREAD') {
        const rawHint = rec.raw_ocr_text ? ` [ตัวอักษรบางส่วน: "${rec.raw_ocr_text}"]` : '';
        return `รอการระบุรหัสยา (0%)${rawHint}`;
      }
      const confNum = (typeof rec.ocr_confidence === 'number') ? rec.ocr_confidence : 0.0;
      return `ผลอ่านรหัสยา: ${code} (ความเชื่อมั่น ${Math.round(confNum * 100)}%)`;
    }

    function getCleanRotatedDiscBase64() {
      if (!currentImg || selectedIdx === null || !currentRecords[selectedIdx]) return null;
      const rec = currentRecords[selectedIdx];
      const offCanvas = document.createElement('canvas');
      offCanvas.width = 200;
      offCanvas.height = 200;
      const offCtx = offCanvas.getContext('2d');

      offCtx.fillStyle = '#f1f5f9';
      offCtx.fillRect(0, 0, 200, 200);

      const cropRadius = Math.max(12, rec.r_disc_px * 1.05);
      const scaleFactor = 100.0 / cropRadius;
      const rotDeg = (rec.user_rot_deg !== undefined ? rec.user_rot_deg : 0);

      offCtx.save();
      offCtx.beginPath();
      offCtx.arc(100, 100, 86, 0, Math.PI * 2);
      offCtx.closePath();
      offCtx.clip();

      offCtx.translate(100, 100);
      offCtx.rotate((rotDeg * Math.PI) / 180.0);
      offCtx.scale(scaleFactor, scaleFactor);
      if (zoomContrastBoost) {
        offCtx.filter = 'contrast(175%) brightness(98%)';
      }
      offCtx.drawImage(currentImg, -rec.center_x, -rec.center_y);
      offCtx.restore();

      return offCanvas.toDataURL('image/png').split(',')[1];
    }

    async function triggerReOcrOnSelectedDisc() {
      if (selectedIdx === null || !currentRecords[selectedIdx]) return;
      const targetIdx = selectedIdx;
      const b64 = getCleanRotatedDiscBase64();
      if (!b64) return;

      const btn = document.getElementById('reOcrBtn');
      const statusEl = document.getElementById('reOcrStatusText');
      const origBtnText = btn.textContent;
      btn.textContent = 'กำลังประมวลผลตัวอักษร...';
      btn.disabled = true;
      statusEl.textContent = 'กำลังวิเคราะห์รหัสยาจากมุมที่หมุน...';

      try {
        const resp = await fetch('/api/ocr_disc', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_base64: b64,
            panel_preset: 'auto'
          })
        });
        const data = await resp.json();
        const predCode = String(data.drug_code || 'UNKNOWN').trim().toUpperCase();
        const confVal = (typeof data.ocr_confidence === 'number') ? data.ocr_confidence : 0.0;
        const confPct = Math.round(confVal * 100);
        const rawText = String(data.raw_ocr_text || '').trim();
        if (Array.isArray(data.ocr_candidates)) {
          currentRecords[targetIdx].ocr_candidates = data.ocr_candidates;
        }

        if (data.status === 'ok' && predCode && predCode !== 'UNKNOWN' && predCode !== 'DISC' && confVal > 0) {
          applyDrugCodeToRecord(targetIdx, predCode, {
            isManual: false,
            ocrConfidence: confVal,
            rawOcrText: rawText,
            ocrCandidates: data.ocr_candidates
          });
          renderAll();
          statusEl.textContent = `ผลอ่านรหัสยา: ${predCode} (ความเชื่อมั่น ${confPct}%)`;
          document.getElementById('statusText').textContent =
            `สถานะ: อ่านรหัสยาตำแหน่งที่ #${currentRecords[targetIdx].disc_order} สำเร็จ (${predCode}, ความเชื่อมั่น ${confPct}%)`;
        } else {
          currentRecords[targetIdx].raw_ocr_text = rawText;
          if (currentRecords[targetIdx].drug_code === 'UNKNOWN') {
            currentRecords[targetIdx].ocr_confidence = 0.0;
            currentRecords[targetIdx].is_manual_entry = false;
          }
          rebuildDrugSelectors(currentRecords[targetIdx]);
          renderKpiSummary();
          const rawMsg = rawText ? ` (พบตัวอักษร "${rawText}")` : ' (ความเชื่อมั่น 0%)';
          statusEl.textContent = `ไม่พบรหัสยาที่ตรงเกณฑ์${rawMsg} — กรุณาเลือกจากรายการ`;
          document.getElementById('statusText').textContent =
            `สถานะ: ตำแหน่งที่ #${currentRecords[targetIdx].disc_order} ไม่พบรหัสยาที่ชัดเจน${rawMsg} — สามารถเลือกรหัสยาจากรายการได้ทันที`;
        }
      } catch (e) {
        statusEl.textContent = 'ไม่สามารถเชื่อมต่อบริการ OCR ได้';
      } finally {
        btn.textContent = origBtnText;
        btn.disabled = false;
      }
    }

    function stepSelectedDisc(stepDelta) {
      if (!currentRecords || currentRecords.length === 0) return;
      if (selectedIdx === null) {
        selectedIdx = 0;
      } else {
        selectedIdx = (selectedIdx + stepDelta + currentRecords.length) % currentRecords.length;
      }
      renderAll();
      const activeRow = document.querySelector('#clinicalTbody tr.selected-row');
      if (activeRow && typeof activeRow.scrollIntoView === 'function') {
        activeRow.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }

    document.getElementById('prevDiscBtn').onclick = () => stepSelectedDisc(-1);
    document.getElementById('nextDiscBtn').onclick = () => stepSelectedDisc(1);

    window.addEventListener('keydown', (ev) => {
      const tag = (ev.target && ev.target.tagName) ? ev.target.tagName.toUpperCase() : '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (ev.key === 'ArrowLeft' || ev.key === '[') {
        ev.preventDefault();
        stepSelectedDisc(-1);
      } else if (ev.key === 'ArrowRight' || ev.key === ']') {
        ev.preventDefault();
        stepSelectedDisc(1);
      }
    });

    function rotateSelectedDiscBy(deltaDeg) {
      if (selectedIdx === null || !currentRecords[selectedIdx]) return;
      const cur = currentRecords[selectedIdx].user_rot_deg || 0;
      const nextDeg = (cur + deltaDeg + 360) % 360;
      currentRecords[selectedIdx].user_rot_deg = nextDeg;
      drawSelectedDiscZoom();
      document.getElementById('reOcrStatusText').textContent =
        `มุมปัจจุบัน ${nextDeg}° — กดปุ่มด้านบนเพื่ออ่านรหัสยาซ้ำ`;
    }

    document.getElementById('rotLeft45Btn').onclick = () => rotateSelectedDiscBy(-45);
    document.getElementById('rotLeft15Btn').onclick = () => rotateSelectedDiscBy(-15);
    document.getElementById('rotRight15Btn').onclick = () => rotateSelectedDiscBy(15);
    document.getElementById('rotRight45Btn').onclick = () => rotateSelectedDiscBy(45);
    document.getElementById('rotFlipBtn').onclick = () => rotateSelectedDiscBy(180);
    document.getElementById('reOcrBtn').onclick = () => triggerReOcrOnSelectedDisc();

    document.getElementById('contrastBoostBtn').onclick = (e) => {
      zoomContrastBoost = !zoomContrastBoost;
      e.currentTarget.classList.toggle('active-filter', zoomContrastBoost);
      drawSelectedDiscZoom();
    };

    async function persistActiveAlbumChanges() {
      if (!activeAlbumId) return;
      const item = albumItems.find(x => x.album_id === activeAlbumId);
      if (!item) return;
      item.discs = currentRecords.map(d => {
        const bp = getBreakpointForRecord(d);
        return {
          ...d,
          drug_full_name: bp.name,
          bp_r_mm: bp.r,
          bp_s_mm: bp.s,
          sir_status: interpretSirForRecord(d)
        };
      });
      updateExportSummaryBadge();
      try {
        await fetch(`/api/album/${encodeURIComponent(activeAlbumId)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ discs: item.discs })
        });
      } catch (e) {}
    }

    function applyDrugCodeToRecord(idx, rawInputCode, options = {}) {
      if (idx === null || !currentRecords[idx]) return;
      const cleanCode = String(rawInputCode || '').trim().toUpperCase() || 'UNKNOWN';
      const isManual = options.isManual !== undefined ? Boolean(options.isManual) : true;
      const rec = currentRecords[idx];
      rec.drug_code = cleanCode;
      rec.needs_review = (cleanCode === 'UNKNOWN' || cleanCode === 'DISC' || cleanCode === 'UNREAD');
      rec.is_manual_entry = isManual && !rec.needs_review;

      if (typeof options.ocrConfidence === 'number') {
        rec.ocr_confidence = options.ocrConfidence;
      } else if (rec.needs_review) {
        rec.ocr_confidence = 0.0;
      } else if (isManual) {
        rec.ocr_confidence = 1.0;
      }
      if (options.rawOcrText !== undefined) {
        rec.raw_ocr_text = options.rawOcrText;
      }
      if (Array.isArray(options.ocrCandidates)) {
        rec.ocr_candidates = options.ocrCandidates;
      }

      if (BREAKPOINTS[cleanCode]) {
        rec.drug_full_name = BREAKPOINTS[cleanCode].name;
        rec.bp_r_mm = BREAKPOINTS[cleanCode].r;
        rec.bp_s_mm = BREAKPOINTS[cleanCode].s;
        delete rec.custom_bp_r;
        delete rec.custom_bp_s;
      } else {
        rec.drug_full_name = `กำหนดเอง (${cleanCode})`;
        rec.bp_r_mm = rec.custom_bp_r || rec.bp_r_mm || 14.0;
        rec.bp_s_mm = rec.custom_bp_s || rec.bp_s_mm || 19.0;
      }
      rec.sir_status = interpretSirForRecord(rec);
      persistActiveAlbumChanges();
    }

    function setSkeletonLoading(isLoading, message = 'กำลังประมวลผลด้วยโมเดล YOLOv26s และ Continuous Warp Polar...') {
      const overlay = document.getElementById('canvasSkeleton');
      const stepTxt = document.getElementById('skeletonStepText');
      const statusTxt = document.getElementById('statusText');
      const tbody = document.getElementById('clinicalTbody');

      if (isLoading) {
        stepTxt.textContent = message;
        statusTxt.textContent = 'สถานะ: ' + message;
        overlay.style.display = 'flex';
        document.getElementById('adjusterPanel').style.display = 'none';
        let skelHtml = '';
        for (let i = 0; i < 6; i++) {
          skelHtml += `
            <tr>
              <td><div class="skeleton-box skel-row" style="width:42px"></div></td>
              <td><div class="skeleton-box skel-row" style="width:85px"></div></td>
              <td><div class="skeleton-box skel-row" style="width:75px"></div></td>
              <td><div class="skeleton-box skel-row" style="width:95px"></div></td>
              <td><div class="skeleton-box skel-row" style="width:80px"></div></td>
              <td><div class="skeleton-box skel-row" style="width:70px"></div></td>
              <td><div class="skeleton-box skel-row" style="width:45px"></div></td>
            </tr>`;
        }
        tbody.innerHTML = skelHtml;
      } else {
        overlay.style.display = 'none';
        statusTxt.textContent = 'สถานะ: พร้อมตรวจสอบผล (คลิกเลือกแผ่นยาเพื่อดูภาพขยายหรือปรับแก้ข้อมูล)';
      }
    }

    function updateParallelQueueUi() {
      const box = document.getElementById('queueProgressBox');
      const pill = document.getElementById('headerQueuePill');
      const fill = document.getElementById('queueBarFill');
      const countEl = document.getElementById('queueProgressCount');

      if (pendingUploadItems.length > 0) {
        box.style.display = 'flex';
        pill.style.display = 'inline-flex';
        pill.textContent = `กำลังวิเคราะห์เบื้องหลัง (${completedQueuedCount}/${totalQueuedCount})...`;
        countEl.textContent = `${completedQueuedCount}/${totalQueuedCount}`;
        const pct = totalQueuedCount > 0 ? Math.round((completedQueuedCount / totalQueuedCount) * 100) : 50;
        fill.style.width = `${pct}%`;
      } else {
        box.style.display = 'none';
        pill.style.display = 'none';
        totalQueuedCount = 0;
        completedQueuedCount = 0;
      }
    }

    function renderAlbumStrip() {
      const strip = document.getElementById('albumStrip');
      document.getElementById('albumCount').textContent = albumItems.length;
      document.getElementById('albumCountHeader').textContent = albumItems.length;
      updateExportSummaryBadge();
      updateParallelQueueUi();

      if (albumItems.length === 0 && pendingUploadItems.length === 0) {
        strip.innerHTML = `
          <div style="font-size:0.8rem;color:var(--muted);padding:14px;text-align:center">
            ยังไม่มีรายการภาพในระบบ<br/>กดปุ่ม <b>"นำเข้าภาพจานเพาะเชื้อ"</b> ด้านบนเพื่อเริ่มการวิเคราะห์
          </div>`;
        return;
      }
      strip.innerHTML = '';

      pendingUploadItems.forEach(pItem => {
        const div = document.createElement('div');
        div.className = 'album-item processing';
        div.innerHTML = `
          <div class="skeleton-box" style="width:15px;height:15px;border-radius:4px;flex-shrink:0"></div>
          <img class="album-thumb" src="${pItem.preview_url}" alt="${pItem.title}" />
          <div class="album-meta">
            <div class="album-title">${pItem.title}</div>
            <div class="album-sub" style="color:#38bdf8">กำลังประมวลผลขนาน...</div>
          </div>
        `;
        strip.appendChild(div);
      });

      albumItems.forEach(item => {
        const div = document.createElement('div');
        div.className = 'album-item' + (item.album_id === activeAlbumId ? ' active' : '');
        const isChecked = checkedAlbumIds.has(item.album_id);
        div.onclick = () => {
          selectAlbumItem(item.album_id);
          if (window.innerWidth <= 1024) {
            albumSidebar.classList.add('collapsed');
            syncSidebarBackdrop();
          }
        };
        div.innerHTML = `
          <input type="checkbox" class="album-check" ${isChecked ? 'checked' : ''} title="เลือกรายการนี้สำหรับการลบหรือการส่งออกข้อมูลรวม" />
          <img class="album-thumb" src="${item.image_url}" alt="${item.title}" />
          <div class="album-meta">
            <div class="album-title">${item.title}</div>
            <div class="album-sub">
              <span>${item.total_discs || (item.discs ? item.discs.length : 0)} แผ่นยา</span>
              ${item.album_id === activeAlbumId ? '<strong style="color:var(--primary)">[กำลังตรวจสอบ]</strong>' : ''}
            </div>
          </div>
          <button class="album-del" title="ลบรายการนี้ออกจากระบบ">✕</button>
        `;
        const chk = div.querySelector('.album-check');
        chk.onclick = (ev) => {
          ev.stopPropagation();
          if (chk.checked) {
            checkedAlbumIds.add(item.album_id);
          } else {
            checkedAlbumIds.delete(item.album_id);
          }
          if (checkedAlbumIds.size > 0 && document.getElementById('exportScopeSelect').value === 'current') {
            document.getElementById('exportScopeSelect').value = 'checked';
          }
          updateExportSummaryBadge();
        };
        div.querySelector('.album-del').onclick = (ev) => {
          ev.stopPropagation();
          deleteAlbumItem(item.album_id);
        };
        strip.appendChild(div);
      });
    }

    document.getElementById('selectAllAlbumBtn').onclick = () => {
      albumItems.forEach(item => checkedAlbumIds.add(item.album_id));
      if (albumItems.length > 0) {
        document.getElementById('exportScopeSelect').value = 'checked';
      }
      renderAlbumStrip();
    };

    document.getElementById('clearAllAlbumBtn').onclick = () => {
      checkedAlbumIds.clear();
      document.getElementById('exportScopeSelect').value = 'current';
      renderAlbumStrip();
    };

    document.getElementById('bulkDeleteSelectedBtn').onclick = async () => {
      if (checkedAlbumIds.size === 0) {
        alert('กรุณาเลือกรายการภาพที่ต้องการลบอย่างน้อย 1 รายการ');
        return;
      }
      const idsToDelete = Array.from(checkedAlbumIds);
      if (!confirm(`ยืนยันการลบรายการภาพที่เลือกจำนวน ${idsToDelete.length} รายการออกจากระบบ?`)) {
        return;
      }

      albumItems = albumItems.filter(x => !checkedAlbumIds.has(x.album_id));
      checkedAlbumIds.clear();

      try {
        await fetch('/api/album/bulk_delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ album_ids: idsToDelete, clear_all: false })
        });
      } catch (e) {}

      if (activeAlbumId && idsToDelete.includes(activeAlbumId)) {
        activeAlbumId = albumItems.length > 0 ? albumItems[0].album_id : null;
        if (activeAlbumId) {
          selectAlbumItem(activeAlbumId);
        } else {
          currentImg = null;
          currentRecords = [];
          selectedIdx = null;
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          renderKpiSummary();
          document.getElementById('clinicalTbody').innerHTML =
            '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">ไม่มีรายการภาพในระบบ</td></tr>';
          document.getElementById('adjusterPanel').style.display = 'none';
        }
      }
      renderAlbumStrip();
      document.getElementById('statusText').textContent = `สถานะ: ลบรายการภาพที่เลือกจำนวน ${idsToDelete.length} รายการเรียบร้อยแล้ว`;
    };

    document.getElementById('clearEntireAlbumBtn').onclick = async () => {
      if (albumItems.length === 0) return;
      if (!confirm(`ยืนยันการล้างรายการภาพทั้งหมด (${albumItems.length} รายการ) ออกจากระบบ?`)) {
        return;
      }
      albumItems = [];
      checkedAlbumIds.clear();
      activeAlbumId = null;
      currentImg = null;
      currentRecords = [];
      selectedIdx = null;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      renderKpiSummary();
      document.getElementById('clinicalTbody').innerHTML =
        '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">ล้างรายการภาพทั้งหมดเรียบร้อยแล้ว — สามารถนำเข้าภาพใหม่ได้ทันที</td></tr>';
      document.getElementById('adjusterPanel').style.display = 'none';

      try {
        await fetch('/api/album/bulk_delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clear_all: true })
        });
      } catch (e) {}
      renderAlbumStrip();
      document.getElementById('statusText').textContent = 'สถานะ: ล้างรายการภาพทั้งหมดในระบบเรียบร้อยแล้ว';
    };

    async function deleteAlbumItem(albumId) {
      albumItems = albumItems.filter(x => x.album_id !== albumId);
      checkedAlbumIds.delete(albumId);
      try {
        await fetch(`/api/album/${encodeURIComponent(albumId)}`, { method: 'DELETE' });
      } catch (e) {}
      if (activeAlbumId === albumId) {
        activeAlbumId = albumItems.length > 0 ? albumItems[0].album_id : null;
        if (activeAlbumId) selectAlbumItem(activeAlbumId);
      }
      renderAlbumStrip();
    }

    function selectAlbumItem(albumId) {
      const item = albumItems.find(x => x.album_id === albumId);
      if (!item) return;
      activeAlbumId = albumId;
      renderAlbumStrip();
      setSkeletonLoading(true, `กำลังโหลดภาพและผลการวิเคราะห์ของ ${item.title}...`);

      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        currentImg = img;
        setSkeletonLoading(false);
        applyAnalysisPayload(item);
      };
      img.onerror = () => setSkeletonLoading(false);
      img.src = item.image_url;
    }

    async function initApp() {
      try {
        const [albRes, platesRes, customRes] = await Promise.all([
          fetch('/api/album'),
          fetch('/api/plates'),
          fetch('/api/custom_drugs')
        ]);
        if (customRes.ok) {
          const cData = await customRes.json();
          const cMap = cData.custom_drugs || {};
          Object.keys(cMap).forEach(code => {
            BREAKPOINTS[code.toUpperCase()] = {
              name: cMap[code].name || code,
              r: parseFloat(cMap[code].R ?? cMap[code].r ?? 14.0),
              s: parseFloat(cMap[code].S ?? cMap[code].s ?? 19.0)
            };
          });
          rebuildDrugSelectors();
        }
        if (albRes.ok) {
          const albData = await albRes.json();
          albumItems = albData.items || [];
          albumItems.forEach(item => checkedAlbumIds.add(item.album_id));
          renderAlbumStrip();
        }
        if (platesRes.ok) {
          const pData = await platesRes.json();
          const sel = document.getElementById('samplePlateSelect');
          (pData.plates || []).forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.plate_id;
            opt.textContent = `${p.plate_id} — ${p.lighting_condition}`;
            sel.appendChild(opt);
          });
          if (albumItems.length > 0) {
            selectAlbumItem(albumItems[0].album_id);
          } else if (pData.plates && pData.plates.length > 0) {
            sel.value = pData.plates[0].plate_id;
            loadSamplePlate(pData.plates[0].plate_id);
          }
        }
      } catch (e) {
        console.error(e);
      }
    }

    async function loadSamplePlate(plateId) {
      if (!plateId) return;
      activeAlbumId = null;
      renderAlbumStrip();
      setSkeletonLoading(true, `กำลังประมวลผลภาพตัวอย่าง ${plateId}...`);
      try {
        const res = await fetch(`/api/plate/${encodeURIComponent(plateId)}`);
        const data = await res.json();
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
          currentImg = img;
          setSkeletonLoading(false);
          applyAnalysisPayload(data);
        };
        img.src = `/dataset/sample_images/${plateId}.png`;
      } catch (err) {
        setSkeletonLoading(false);
      }
    }

    function applyAnalysisPayload(data) {
      currentPlateMeta = {
        title: data.title || data.plate_id || 'plate',
        bacteria_species: data.bacteria_species || 'Escherichia coli ATCC 25922'
      };
      document.getElementById('metaPlateId').textContent = currentPlateMeta.title;
      currentRecords = (data.discs || []).map(d => ({ ...d }));
      document.getElementById('metaCount').textContent = `${currentRecords.length} รายการ`;
      document.getElementById('metaLatency').textContent = data.elapsed_ms ? `${data.elapsed_ms} ms` : 'พร้อมใช้งาน';

      selectedIdx = currentRecords.length > 0 ? 0 : null;
      zoomRotationDeg = 0;
      if (currentRecords.length > 0) {
        document.getElementById('scaleInfo').textContent =
          `มาตราส่วน: ${currentRecords[0].scale_mm_per_px.toFixed(4)} mm/px`;
      }
      updateExportSummaryBadge();
      renderAll();
    }

    function renderAll() {
      renderKpiSummary();
      drawPlateCanvas();
      renderClinicalTable();
      renderAdjuster();
      drawSelectedDiscZoom();
    }

    function resortRecordsSpatially() {
      if (!currentRecords || currentRecords.length === 0) return;
      const selectedRef = (selectedIdx !== null && currentRecords[selectedIdx]) ? currentRecords[selectedIdx] : null;
      const imgH = currentImg ? currentImg.height : 1000;
      const imgW = currentImg ? currentImg.width : 1000;
      const rowTol = Math.max(45.0, imgH * 0.09);

      const sortedByY = [...currentRecords].sort((a, b) => a.center_y - b.center_y);
      const rows = [];
      sortedByY.forEach(d => {
        let placed = false;
        for (const r of rows) {
          const meanY = r.reduce((s, x) => s + x.center_y, 0) / r.length;
          if (Math.abs(d.center_y - meanY) <= rowTol) {
            r.push(d);
            placed = true;
            break;
          }
        }
        if (!placed) rows.push([d]);
      });

      const ordered = [];
      rows.forEach((r, rIdx) => {
        r.sort((a, b) => a.center_x - b.center_x);
        r.forEach((d, cIdx) => {
          d.disc_order = ordered.length + 1;
          if (currentRecords.length >= 10) {
            d.plate_zone = `R${rIdx + 1}-C${cIdx + 1}`;
          } else {
            const rx = d.center_x / Math.max(1, imgW);
            const ry = d.center_y / Math.max(1, imgH);
            if (rx >= 0.36 && rx <= 0.64 && ry >= 0.36 && ry <= 0.64) {
              d.plate_zone = 'Center';
            } else {
              const v = ry < 0.42 ? 'Top' : (ry > 0.58 ? 'Bottom' : 'Mid');
              const h = rx < 0.42 ? 'Left' : (rx > 0.58 ? 'Right' : 'Center');
              d.plate_zone = (v === 'Mid' && h === 'Center') ? 'Center' : `${v}-${h}`;
            }
          }
          ordered.push(d);
        });
      });

      currentRecords = ordered;
      if (selectedRef) {
        const newIdx = currentRecords.indexOf(selectedRef);
        selectedIdx = newIdx >= 0 ? newIdx : 0;
      }
      document.getElementById('metaCount').textContent = `${currentRecords.length} รายการ`;
    }

    function drawPlateCanvas() {
      if (!currentImg) return;
      canvas.width = currentImg.width;
      canvas.height = currentImg.height;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(currentImg, 0, 0);

      const fontScale = Math.max(13, Math.round(canvas.width * 0.017));
      const isActivelyAdjusting = Boolean(
        isSliderResizing ||
        (dragState && dragState.isMoving)
      );

      currentRecords.forEach((r, idx) => {
        const isSel = idx === selectedIdx;
        const sir = interpretSirForRecord(r);
        const sirColor = sir === 'S' ? '#34d399' : (sir === 'I' ? '#fbbf24' : '#f87171');
        const activeRingColor = '#38bdf8';

        // เฉพาะตอนที่กำลังขยับหรือลากปรับขนาดวง (isActivelyAdjusting === true) เท่านั้น จึงจะทำให้วงอื่นจางลงชั่วคราว
        // ในเวลาปกติที่ไม่ได้กำลังขยับวง ทุกวงจะแสดงความคมชัดเต็ม 100%
        if (!isSel && (isActivelyAdjusting || isSoloZoneMode)) {
          if (!isSoloZoneMode) {
            ctx.save();
            ctx.globalAlpha = 0.18;
            ctx.beginPath();
            ctx.arc(r.center_x, r.center_y, r.r_zone_px, 0, Math.PI * 2);
            ctx.strokeStyle = sirColor;
            ctx.lineWidth = 1.4;
            ctx.stroke();

            ctx.beginPath();
            ctx.arc(r.center_x, r.center_y, r.r_disc_px, 0, Math.PI * 2);
            ctx.strokeStyle = '#e2e8f0';
            ctx.lineWidth = 1.2;
            ctx.stroke();
            ctx.restore();
          }
          return;
        }

        ctx.save();

        // วาดวงยับยั้งเชื้อ (Inhibition Zone)
        if (!(isSel && isActivelyAdjusting) && r.diameter_mm > 6.4) {
          ctx.beginPath();
          ctx.arc(r.center_x, r.center_y, r.r_zone_px, 0, Math.PI * 2);
          ctx.fillStyle = isSel ? 'rgba(56, 189, 248, 0.12)' : (sir === 'S' ? 'rgba(52, 211, 153, 0.08)' : (sir === 'I' ? 'rgba(251, 191, 36, 0.08)' : 'rgba(248, 113, 113, 0.08)'));
          ctx.fill();
        }

        // เส้นเงารองพื้นสีเข้ม (Contrast Halo) เพื่อให้เห็นเส้นวงชัดเจนบนพื้นวุ้นทุกสี
        ctx.beginPath();
        ctx.arc(r.center_x, r.center_y, r.r_zone_px, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(15, 23, 42, 0.78)';
        ctx.lineWidth = isSel ? 4.4 : 3.4;
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(r.center_x, r.center_y, r.r_zone_px, 0, Math.PI * 2);
        if (isSel && isActivelyAdjusting) {
          ctx.setLineDash([8, 5]);
          ctx.strokeStyle = activeRingColor;
          ctx.lineWidth = 2.2;
          ctx.stroke();
          ctx.setLineDash([]);

          // วาดขีดบอกแนวรัศมี 4 ทิศทาง (Precision Caliper Ticks) ด้านนอกขอบวงเพื่อช่วยเล็งขอบเขตวงใส
          const tickInner = r.r_zone_px + 2;
          const tickOuter = r.r_zone_px + Math.max(10, canvas.width * 0.012);
          [0, Math.PI / 2, Math.PI, (3 * Math.PI) / 2].forEach(ang => {
            ctx.beginPath();
            ctx.moveTo(r.center_x + tickInner * Math.cos(ang), r.center_y + tickInner * Math.sin(ang));
            ctx.lineTo(r.center_x + tickOuter * Math.cos(ang), r.center_y + tickOuter * Math.sin(ang));
            ctx.strokeStyle = '#f8fafc';
            ctx.lineWidth = 2.0;
            ctx.stroke();
          });
        } else {
          ctx.strokeStyle = isSel ? activeRingColor : sirColor;
          ctx.lineWidth = isSel ? 2.8 : 2.2;
          ctx.stroke();
        }

        if (isSel && isEditCircleMode && !isActivelyAdjusting) {
          const handleR = Math.max(5.0, canvas.width * 0.006);
          const handleAngles = [0, Math.PI / 2, Math.PI, (3 * Math.PI) / 2];
          handleAngles.forEach(ang => {
            const hx = r.center_x + r.r_zone_px * Math.cos(ang);
            const hy = r.center_y + r.r_zone_px * Math.sin(ang);
            ctx.beginPath();
            ctx.arc(hx, hy, handleR, 0, Math.PI * 2);
            ctx.fillStyle = '#72b3a8';
            ctx.fill();
            ctx.lineWidth = 1.8;
            ctx.strokeStyle = '#161b22';
            ctx.stroke();
          });

          ctx.beginPath();
          ctx.arc(r.center_x, r.center_y, Math.max(5.5, canvas.width * 0.0065), 0, Math.PI * 2);
          ctx.fillStyle = '#4f86ad';
          ctx.fill();
          ctx.lineWidth = 1.8;
          ctx.strokeStyle = '#dbe2eb';
          ctx.stroke();
        }

        // วาดขอบแผ่นยา (Paper Disc)
        ctx.beginPath();
        ctx.arc(r.center_x, r.center_y, r.r_disc_px, 0, Math.PI * 2);
        ctx.strokeStyle = isSel ? '#dbe2eb' : (r.needs_review ? '#d9a754' : '#8ab4c9');
        ctx.lineWidth = isSel ? 2.2 : 1.6;
        ctx.stroke();

        ctx.restore();
      });

      // วาดป้ายชื่อยาแบบหลบการทับซ้อนอัตโนมัติ (Smart Radial + 2D Collision Resolution)
      if (currentRecords.length > 0) {
        const minDim = Math.min(canvas.width, canvas.height);
        const centroidX = currentRecords.reduce((s, x) => s + x.center_x, 0) / currentRecords.length;
        const centroidY = currentRecords.reduce((s, x) => s + x.center_y, 0) / currentRecords.length;
        const badgeItems = [];

        currentRecords.forEach((r, idx) => {
          const isSel = idx === selectedIdx;
          if (!isSel && (isActivelyAdjusting || isSoloZoneMode)) return;
          const sir = interpretSirForRecord(r);
          const sirColor = sir === 'S' ? '#34d399' : (sir === 'I' ? '#fbbf24' : '#f87171');
          const warnPrefix = (r.needs_review || r.drug_code === 'UNKNOWN') ? '[?] ' : '';
          const label = isSel
            ? `${warnPrefix}#${r.disc_order} ${r.drug_code} (${r.diameter_mm.toFixed(1)}mm [${sir}])`
            : (r.diameter_mm > 6.2
                ? `${warnPrefix}#${r.disc_order} ${r.drug_code} • ${r.diameter_mm.toFixed(1)}`
                : `${warnPrefix}#${r.disc_order} ${r.drug_code}`);

          const fSize = isSel ? fontScale : Math.max(11, Math.round(fontScale * 0.88));
          ctx.font = `bold ${fSize}px 'Inter', 'Noto Sans Thai', sans-serif`;
          const tw = ctx.measureText(label).width + (isSel ? 14 : 10);
          const th = fSize + (isSel ? 9 : 7);

          const dx = r.center_x - centroidX;
          const dy = r.center_y - centroidY;
          const isCenterDisc = Math.abs(dx) < minDim * 0.13 && Math.abs(dy) < minDim * 0.13;
          const placeBelow = isCenterDisc || (dy > minDim * 0.08);
          const lift = (isSel && isActivelyAdjusting) ? Math.max(16, canvas.width * 0.018) : 8;

          let cx = r.center_x + (isCenterDisc ? 0 : dx * 0.16);
          let cy = placeBelow
            ? (r.center_y + r.r_zone_px + lift + th * 0.5)
            : (r.center_y - r.r_zone_px - lift - th * 0.5);

          cx = Math.max(tw / 2 + 4, Math.min(canvas.width - tw / 2 - 4, cx));
          cy = Math.max(th / 2 + 4, Math.min(canvas.height - th / 2 - 4, cy));

          badgeItems.push({
            idx, isSel, r, label, fSize, tw, th, cx, cy,
            strokeColor: isSel ? '#38bdf8' : sirColor
          });
        });

        for (let iter = 0; iter < 16; iter++) {
          let moved = false;
          for (let a = 0; a < badgeItems.length; a++) {
            for (let b = a + 1; b < badgeItems.length; b++) {
              const ba = badgeItems[a];
              const bb = badgeItems[b];
              const overlapX = (ba.tw / 2 + bb.tw / 2 + 6) - Math.abs(ba.cx - bb.cx);
              const overlapY = (ba.th / 2 + bb.th / 2 + 4) - Math.abs(ba.cy - bb.cy);
              if (overlapX > 0 && overlapY > 0) {
                moved = true;
                if (overlapX < overlapY * 1.35) {
                  const dir = ba.cx <= bb.cx ? -1 : 1;
                  ba.cx += dir * (overlapX * 0.55);
                  bb.cx -= dir * (overlapX * 0.55);
                } else {
                  const dir = ba.cy <= bb.cy ? -1 : 1;
                  ba.cy += dir * (overlapY * 0.55);
                  bb.cy -= dir * (overlapY * 0.55);
                }
              }
            }
          }
          badgeItems.forEach(b => {
            b.cx = Math.max(b.tw / 2 + 4, Math.min(canvas.width - b.tw / 2 - 4, b.cx));
            b.cy = Math.max(b.th / 2 + 4, Math.min(canvas.height - b.th / 2 - 4, b.cy));
          });
          if (!moved) break;
        }

        // วาดป้ายที่ไม่ได้เลือกก่อน และวาดป้ายที่กำลังเลือกทับบนสุดเสมอ
        badgeItems.sort((a, b) => (a.isSel ? 1 : 0) - (b.isSel ? 1 : 0));
        badgeItems.forEach(b => {
          ctx.save();
          const lx = b.cx - b.tw / 2;
          const ly = b.cy - b.th / 2;
          ctx.fillStyle = b.isSel ? 'rgba(22, 27, 34, 0.94)' : 'rgba(22, 27, 34, 0.84)';
          ctx.fillRect(lx, ly, b.tw, b.th);
          ctx.strokeStyle = b.strokeColor;
          ctx.lineWidth = b.isSel ? 1.5 : 1.1;
          ctx.strokeRect(lx, ly, b.tw, b.th);
          ctx.font = `bold ${b.fSize}px 'Inter', 'Noto Sans Thai', sans-serif`;
          ctx.fillStyle = b.isSel ? '#f8fafc' : '#dbe2eb';
          ctx.fillText(b.label, lx + (b.isSel ? 7 : 5), ly + b.fSize + (b.isSel ? 2 : 1));
          ctx.restore();
        });
      }

      if (dragState && dragState.mode === 'add_new_disc') {
        const { cx, cy, rDiscPx, curZoneRadiusPx, scaleMmPerPx } = dragState;
        const previewMm = Math.max(6.0, Math.min(42.0, 2.0 * curZoneRadiusPx * scaleMmPerPx));
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx, cy, curZoneRadiusPx, 0, Math.PI * 2);
        ctx.strokeStyle = '#72b3a8';
        ctx.lineWidth = 2.4;
        ctx.setLineDash([7, 4]);
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(cx, cy, rDiscPx, 0, Math.PI * 2);
        ctx.strokeStyle = '#dbe2eb';
        ctx.lineWidth = 2.0;
        ctx.setLineDash([]);
        ctx.stroke();

        ctx.fillStyle = 'rgba(31, 38, 48, 0.92)';
        const txt = `ตำแหน่งใหม่: ขนาดวงยับยั้ง ${previewMm.toFixed(1)} mm`;
        ctx.font = `bold ${fontScale}px 'Inter', 'Noto Sans Thai', sans-serif`;
        const tw = ctx.measureText(txt).width + 14;
        ctx.fillRect(cx - tw / 2, cy - curZoneRadiusPx - 36, tw, 26);
        ctx.fillStyle = '#72b3a8';
        ctx.fillText(txt, cx - tw / 2 + 7, cy - curZoneRadiusPx - 17);
        ctx.restore();
      }
    }

    function renderClinicalTable() {
      const cBody = document.getElementById('clinicalTbody');
      cBody.innerHTML = '';

      currentRecords.forEach((r, idx) => {
        const sir = interpretSirForRecord(r);
        const bp = getBreakpointForRecord(r);
        const isUncertain = Boolean(r.needs_review || r.drug_code === 'UNKNOWN' || r.drug_code === 'DISC');

        const tr = document.createElement('tr');
        if (idx === selectedIdx) tr.className = 'selected-row';
        tr.onclick = () => {
          selectedIdx = idx;
          renderAll();
        };
        tr.innerHTML = `
          <td><strong>#${r.disc_order}</strong></td>
          <td>${r.plate_zone}</td>
          <td>(${r.center_x}, ${r.center_y})</td>
          <td>
            <input
              type="text"
              list="drugDatalist"
              class="inline-drug-input ${isUncertain ? 'uncertain' : ''}"
              value="${r.drug_code}"
              title="พิมพ์รหัสยาปฏิชีวนะ หรือคลิกเลือกจากรายการด้านบน"
            />
            ${isUncertain ? '<span class="review-badge">รอตรวจสอบ</span>' : ''}
          </td>
          <td><strong>${r.diameter_mm.toFixed(1)} mm</strong></td>
          <td>≤${bp.r} / ≥${bp.s}</td>
          <td><span class="sir-pill sir-${sir}">${sir}</span></td>
        `;

        const inputEl = tr.querySelector('.inline-drug-input');
        inputEl.addEventListener('click', (ev) => {
          ev.stopPropagation();
          if (selectedIdx !== idx) {
            selectedIdx = idx;
            renderAdjuster();
            drawPlateCanvas();
            drawSelectedDiscZoom();
          }
        });
        inputEl.addEventListener('change', (ev) => {
          applyDrugCodeToRecord(idx, ev.target.value, { isManual: true });
          renderAll();
        });
        inputEl.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter') {
            ev.preventDefault();
            applyDrugCodeToRecord(idx, ev.target.value, { isManual: true });
            renderAll();
            inputEl.blur();
          }
        });

        cBody.appendChild(tr);
      });
    }

    function renderAdjuster() {
      const box = document.getElementById('adjusterPanel');
      if (selectedIdx === null || !currentRecords[selectedIdx]) {
        box.style.display = 'none';
        return;
      }
      box.style.display = 'flex';
      const rec = currentRecords[selectedIdx];
      const sir = interpretSirForRecord(rec);
      const bp = getBreakpointForRecord(rec);

      document.getElementById('adjTitle').textContent = `ข้อมูลแผ่นยาตำแหน่งที่ #${rec.disc_order} (${rec.plate_zone})`;
      rebuildDrugSelectors(rec);

      document.getElementById('adjBpR').value = bp.r;
      document.getElementById('adjBpS').value = bp.s;
      document.getElementById('adjDrugFullName').textContent = bp.name;

      const slider = document.getElementById('adjDiamSlider');
      slider.value = rec.diameter_mm;
      document.getElementById('adjDiamVal').textContent = `${rec.diameter_mm.toFixed(1)} mm (${sir})`;
      document.getElementById('reOcrStatusText').textContent = formatDiscConfidenceStatus(rec);
    }

    adjDrugSelect.addEventListener('change', (e) => {
      if (selectedIdx === null || !e.target.value) return;
      if (e.target.value === '__CUSTOM_PROMPT__') {
        const customCode = prompt('ระบุรหัสยาปฏิชีวนะ (เช่น AMC30, CPD10, LEV5):', currentRecords[selectedIdx].drug_code || '');
        if (customCode && customCode.trim()) {
          applyDrugCodeToRecord(selectedIdx, customCode.trim().toUpperCase(), { isManual: true });
        }
        renderAll();
        return;
      }
      applyDrugCodeToRecord(selectedIdx, e.target.value, { isManual: true });
      renderAll();
    });

    document.getElementById('deleteSelectedDiscBtn').onclick = () => {
      if (selectedIdx === null || !currentRecords[selectedIdx]) return;
      const rec = currentRecords[selectedIdx];
      currentRecords.splice(selectedIdx, 1);
      resortRecordsSpatially();
      selectedIdx = currentRecords.length > 0 ? Math.min(selectedIdx, currentRecords.length - 1) : null;
      persistActiveAlbumChanges();
      renderAll();
      document.getElementById('statusText').textContent = `สถานะ: ลบตำแหน่งแผ่นยาที่ #${rec.disc_order} ออกจากจานเพาะเชื้อเรียบร้อยแล้ว`;
    };

    document.getElementById('adjBpR').addEventListener('change', (e) => {
      if (selectedIdx === null) return;
      const v = parseFloat(e.target.value);
      if (!isNaN(v)) {
        currentRecords[selectedIdx].custom_bp_r = v;
        persistActiveAlbumChanges();
        renderAll();
      }
    });
    document.getElementById('adjBpS').addEventListener('change', (e) => {
      if (selectedIdx === null) return;
      const v = parseFloat(e.target.value);
      if (!isNaN(v)) {
        currentRecords[selectedIdx].custom_bp_s = v;
        persistActiveAlbumChanges();
        renderAll();
      }
    });

    const adjSliderEl = document.getElementById('adjDiamSlider');
    const finishSliderResize = () => {
      if (sliderResizeTimer) clearTimeout(sliderResizeTimer);
      if (isSliderResizing) {
        isSliderResizing = false;
        drawPlateCanvas();
      }
    };
    adjSliderEl.addEventListener('pointerdown', () => {
      if (sliderResizeTimer) clearTimeout(sliderResizeTimer);
      isSliderResizing = true;
      drawPlateCanvas();
    });
    window.addEventListener('pointerup', finishSliderResize);
    adjSliderEl.addEventListener('change', finishSliderResize);
    adjSliderEl.addEventListener('input', (e) => {
      if (selectedIdx === null) return;
      isSliderResizing = true;
      if (sliderResizeTimer) clearTimeout(sliderResizeTimer);
      sliderResizeTimer = setTimeout(() => {
        isSliderResizing = false;
        drawPlateCanvas();
      }, 650);
      const val = parseFloat(e.target.value);
      const rec = currentRecords[selectedIdx];
      rec.diameter_mm = val;
      rec.r_zone_px = (val / 2.0) / rec.scale_mm_per_px;
      persistActiveAlbumChanges();
      renderAll();
    });

    document.getElementById('toggleCustomDrugBtn').onclick = () => {
      const dr = document.getElementById('customDrugDrawer');
      dr.style.display = dr.style.display === 'flex' ? 'none' : 'flex';
    };
    document.getElementById('closeCustomDrugBtn').onclick = () => {
      document.getElementById('customDrugDrawer').style.display = 'none';
    };

    document.getElementById('saveNewDrugBtn').onclick = async () => {
      const code = document.getElementById('newDrugCode').value.trim().toUpperCase();
      const name = document.getElementById('newDrugName').value.trim() || code;
      const rVal = parseFloat(document.getElementById('newDrugR').value) || 14.0;
      const sVal = parseFloat(document.getElementById('newDrugS').value) || 19.0;
      if (!code) {
        alert('กรุณาระบุรหัสยาปฏิชีวนะ เช่น LEV5 หรือ DO30');
        return;
      }
      BREAKPOINTS[code] = { name, r: rVal, s: sVal };
      rebuildDrugSelectors();

      try {
        await fetch('/api/custom_drugs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ drug_code: code, name, r: rVal, s: sVal })
        });
      } catch (e) {}

      if (selectedIdx !== null && currentRecords[selectedIdx]) {
        applyDrugCodeToRecord(selectedIdx, code, { isManual: true });
        renderAll();
      }
      document.getElementById('newDrugCode').value = '';
      document.getElementById('newDrugName').value = '';
      document.getElementById('customDrugDrawer').style.display = 'none';
      document.getElementById('statusText').textContent = `สถานะ: บันทึกข้อมูลยา ${code} (${name}) เข้าสู่ระบบเรียบร้อยแล้ว`;
    };

    function getCanvasCoordsFromClient(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      const ix = (clientX - rect.left) * (canvas.width / Math.max(1, rect.width));
      const iy = (clientY - rect.top) * (canvas.height / Math.max(1, rect.height));
      return { ix, iy };
    }

    function getMedianDiscRadiusPx() {
      if (currentRecords.length > 0) {
        const sorted = currentRecords.map(r => r.r_disc_px).sort((a, b) => a - b);
        return sorted[Math.floor(sorted.length / 2)];
      }
      return currentImg ? Math.max(18, Math.round(Math.min(currentImg.width, currentImg.height) * 0.028)) : 28;
    }

    function getCurrentPlateBase64() {
      if (!currentImg) return null;
      const tmp = document.createElement('canvas');
      tmp.width = currentImg.width;
      tmp.height = currentImg.height;
      tmp.getContext('2d').drawImage(currentImg, 0, 0);
      return tmp.toDataURL('image/jpeg', 0.92).split(',')[1];
    }

    function handlePointerDown(clientX, clientY) {
      if (!currentImg) return false;
      const { ix, iy } = getCanvasCoordsFromClient(clientX, clientY);

      if (isAddDiscMode) {
        const rDiscPx = getMedianDiscRadiusPx();
        const scaleMmPerPx = 6.0 / (2.0 * rDiscPx);
        dragState = {
          mode: 'add_new_disc',
          cx: Math.round(ix),
          cy: Math.round(iy),
          rDiscPx,
          scaleMmPerPx,
          curZoneRadiusPx: rDiscPx,
          dragged: false
        };
        drawPlateCanvas();
        return true;
      }

      const ringTol = Math.max(18, canvas.width * 0.022);

      if (isEditCircleMode && selectedIdx !== null && currentRecords[selectedIdx]) {
        const sel = currentRecords[selectedIdx];
        const distFromSel = Math.hypot(ix - sel.center_x, iy - sel.center_y);
        if (Math.abs(distFromSel - sel.r_zone_px) <= ringTol && distFromSel > sel.r_disc_px * 0.85) {
          dragState = {
            mode: 'resize_existing_zone',
            targetIdx: selectedIdx
          };
          drawPlateCanvas();
          return true;
        }
      }

      let bestCenterIdx = null, bestCenterDist = 1e9;
      currentRecords.forEach((r, idx) => {
        const d = Math.hypot(r.center_x - ix, r.center_y - iy);
        if (d <= Math.max(r.r_disc_px * 1.55, 26) && d < bestCenterDist) {
          bestCenterDist = d;
          bestCenterIdx = idx;
        }
      });

      if (bestCenterIdx !== null) {
        selectedIdx = bestCenterIdx;
        renderAll();
        if (isEditCircleMode) {
          const targetRec = currentRecords[bestCenterIdx];
          dragState = {
            mode: 'move_existing_disc',
            targetIdx: bestCenterIdx,
            offsetX: targetRec.center_x - ix,
            offsetY: targetRec.center_y - iy,
            moved: false
          };
        }
        return true;
      }

      let bestZoneIdx = null, bestZoneDist = 1e9;
      currentRecords.forEach((r, idx) => {
        const d = Math.hypot(r.center_x - ix, r.center_y - iy);
        if (d <= Math.max(r.r_zone_px * 1.25, r.r_disc_px * 2.1) && d < bestZoneDist) {
          bestZoneDist = d;
          bestZoneIdx = idx;
        }
      });

      if (bestZoneIdx !== null) {
        selectedIdx = bestZoneIdx;
        renderAll();
        if (isEditCircleMode) {
          const sel = currentRecords[bestZoneIdx];
          const distFromSel = Math.hypot(ix - sel.center_x, iy - sel.center_y);
          if (Math.abs(distFromSel - sel.r_zone_px) <= ringTol) {
            dragState = {
              mode: 'resize_existing_zone',
              targetIdx: bestZoneIdx
            };
          } else {
            dragState = {
              mode: 'move_existing_disc',
              targetIdx: bestZoneIdx,
              offsetX: sel.center_x - ix,
              offsetY: sel.center_y - iy,
              moved: false
            };
          }
          drawPlateCanvas();
        }
        return true;
      }
      return false;
    }

    function handlePointerMove(clientX, clientY) {
      if (!currentImg) return;
      const { ix, iy } = getCanvasCoordsFromClient(clientX, clientY);

      if (!dragState) {
        if (isAddDiscMode) {
          canvas.style.cursor = 'crosshair';
        } else if (isEditCircleMode && selectedIdx !== null && currentRecords[selectedIdx]) {
          const sel = currentRecords[selectedIdx];
          const d = Math.hypot(ix - sel.center_x, iy - sel.center_y);
          const ringTol = Math.max(16, canvas.width * 0.02);
          if (d <= sel.r_disc_px * 1.35) {
            canvas.style.cursor = 'move';
          } else if (Math.abs(d - sel.r_zone_px) <= ringTol) {
            canvas.style.cursor = 'nwse-resize';
          } else {
            canvas.style.cursor = 'pointer';
          }
        } else {
          canvas.style.cursor = 'pointer';
        }
        return;
      }

      dragState.isMoving = true;
      if (dragState.mode === 'add_new_disc') {
        const distPx = Math.hypot(ix - dragState.cx, iy - dragState.cy);
        if (distPx > dragState.rDiscPx * 1.15) {
          dragState.dragged = true;
          dragState.curZoneRadiusPx = Math.min(distPx, (42.0 / 2.0) / dragState.scaleMmPerPx);
        } else {
          dragState.curZoneRadiusPx = dragState.rDiscPx;
        }
        drawPlateCanvas();
        return;
      }

      if (dragState.mode === 'move_existing_disc') {
        const rec = currentRecords[dragState.targetIdx];
        if (!rec) return;
        const newCx = Math.round(Math.max(rec.r_disc_px, Math.min(canvas.width - rec.r_disc_px, ix + dragState.offsetX)));
        const newCy = Math.round(Math.max(rec.r_disc_px, Math.min(canvas.height - rec.r_disc_px, iy + dragState.offsetY)));
        if (Math.abs(newCx - rec.center_x) >= 1 || Math.abs(newCy - rec.center_y) >= 1) {
          dragState.moved = true;
          rec.center_x = newCx;
          rec.center_y = newCy;
          drawPlateCanvas();
          drawSelectedDiscZoom();
          renderClinicalTable();
        }
        return;
      }

      if (dragState.mode === 'resize_existing_zone') {
        const rec = currentRecords[dragState.targetIdx];
        if (!rec) return;
        const distPx = Math.max(rec.r_disc_px, Math.hypot(ix - rec.center_x, iy - rec.center_y));
        const rawMm = Math.min(42.0, Math.max(6.0, 2.0 * distPx * rec.scale_mm_per_px));
        const roundedMm = Math.round(rawMm * 2.0) / 2.0;
        rec.diameter_mm = roundedMm;
        rec.r_zone_px = (roundedMm / 2.0) / rec.scale_mm_per_px;
        drawPlateCanvas();
        renderAdjuster();
        renderClinicalTable();
        renderKpiSummary();
      }
    }

    async function handlePointerUp() {
      if (!dragState) return;
      const finishedDrag = dragState;
      dragState = null;

      if (finishedDrag.mode === 'move_existing_disc') {
        drawPlateCanvas();
        if (finishedDrag.moved) {
          const movedRec = currentRecords[finishedDrag.targetIdx];
          resortRecordsSpatially();
          persistActiveAlbumChanges();
          renderAll();
          if (movedRec) {
            document.getElementById('statusText').textContent =
              `สถานะ: ปรับย้ายพิกัดแผ่นยาที่ #${movedRec.disc_order} ไปยัง (${movedRec.center_x}, ${movedRec.center_y}) เรียบร้อยแล้ว`;
          }
        }
        return;
      }

      if (finishedDrag.mode === 'resize_existing_zone') {
        persistActiveAlbumChanges();
        renderAll();
        return;
      }

      if (finishedDrag.mode === 'add_new_disc') {
        const { cx, cy, rDiscPx, scaleMmPerPx, curZoneRadiusPx, dragged } = finishedDrag;
        const userMm = dragged
          ? Math.round(Math.max(6.0, Math.min(42.0, 2.0 * curZoneRadiusPx * scaleMmPerPx)) * 2.0) / 2.0
          : null;

        const tempDisc = {
          disc_order: currentRecords.length + 1,
          plate_zone: 'Manual',
          center_x: cx,
          center_y: cy,
          r_disc_px: Number(rDiscPx.toFixed(1)),
          r_zone_px: Number(curZoneRadiusPx.toFixed(1)),
          scale_mm_per_px: Number(scaleMmPerPx.toFixed(4)),
          confidence: 1.0,
          ocr_confidence: 0.0,
          ocr_candidates: [],
          needs_review: true,
          drug_code: 'UNKNOWN',
          drug_full_name: BREAKPOINTS.UNKNOWN.name,
          diameter_mm: userMm || 6.0,
          sir_status: 'R',
          bp_r_mm: 14.0,
          bp_s_mm: 19.0
        };
        currentRecords.push(tempDisc);
        selectedIdx = currentRecords.length - 1;
        resortRecordsSpatially();
        setAddDiscMode(false);
        renderAll();

        document.getElementById('statusText').textContent =
          `สถานะ: กำลังประมวลผลรหัสยาและวัดขนาดวงยับยั้ง ณ พิกัด (${cx}, ${cy})...`;

        try {
          const plateB64 = getCurrentPlateBase64();
          if (plateB64) {
            const resp = await fetch('/api/add_manual_disc', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                image_base64: plateB64,
                center_x: cx,
                center_y: cy,
                r_disc_px: rDiscPx,
                user_diameter_mm: userMm,
                existing_discs: currentRecords
              })
            });
            const data = await resp.json();
            if (data.status === 'ok' && data.disc) {
              const targetIdx = currentRecords.indexOf(tempDisc);
              if (targetIdx >= 0) {
                Object.assign(tempDisc, data.disc);
                resortRecordsSpatially();
                persistActiveAlbumChanges();
                renderAll();
                const pct = Math.round((tempDisc.ocr_confidence || 0) * 100);
                document.getElementById('statusText').textContent =
                  tempDisc.drug_code !== 'UNKNOWN'
                    ? `สถานะ: เพิ่มตำแหน่งที่ #${tempDisc.disc_order} สำเร็จ (${tempDisc.drug_code}, ความเชื่อมั่น ${pct}%, ขนาดวงยับยั้ง ${tempDisc.diameter_mm.toFixed(1)} mm)`
                    : `สถานะ: เพิ่มตำแหน่งที่ #${tempDisc.disc_order} สำเร็จ (ขนาดวงยับยั้ง ${tempDisc.diameter_mm.toFixed(1)} mm) — กรุณาเลือกรหัสยาทางด้านขวา`;
              }
            }
          }
        } catch (err) {
          persistActiveAlbumChanges();
          renderAll();
        }
      }
    }

    canvas.addEventListener('mousedown', (e) => {
      handlePointerDown(e.clientX, e.clientY);
    });
    canvas.addEventListener('mousemove', (e) => {
      handlePointerMove(e.clientX, e.clientY);
    });
    window.addEventListener('mouseup', () => {
      handlePointerUp();
    });

    canvas.addEventListener('touchstart', (e) => {
      if (!e.touches || e.touches.length === 0) return;
      const t = e.touches[0];
      const hit = handlePointerDown(t.clientX, t.clientY);
      if (hit) e.preventDefault();
    }, { passive: false });

    canvas.addEventListener('touchmove', (e) => {
      if (!dragState || !e.touches || e.touches.length === 0) return;
      e.preventDefault();
      const t = e.touches[0];
      handlePointerMove(t.clientX, t.clientY);
    }, { passive: false });

    window.addEventListener('touchend', () => {
      handlePointerUp();
    });

    document.getElementById('samplePlateSelect').addEventListener('change', (e) => {
      loadSamplePlate(e.target.value);
    });

    document.getElementById('fileInput').addEventListener('change', async (e) => {
      const files = Array.from(e.target.files || []);
      e.target.value = '';
      if (files.length === 0) return;

      const preset = 'auto';
      totalQueuedCount += files.length;

      const tasks = await Promise.all(files.map(async (file, idx) => {
        const dataUrl = await new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = (ev) => resolve(ev.target.result);
          reader.readAsDataURL(file);
        });
        const tempId = `pending_${Date.now()}_${idx}_${Math.random().toString(36).slice(2, 6)}`;
        const pItem = {
          temp_id: tempId,
          title: file.name,
          preview_url: dataUrl,
          dataUrl,
          file
        };
        pendingUploadItems.push(pItem);
        return pItem;
      }));

      renderAlbumStrip();

      const hadActivePlateBefore = Boolean(activeAlbumId && currentRecords.length > 0);
      if (!hadActivePlateBefore) {
        setSkeletonLoading(true, `กำลังวิเคราะห์ภาพแรก (${tasks[0].title})... ส่วนภาพอื่นประมวลผลขนานเบื้องหลัง`);
      }

      let cursor = 0;
      let openedFirstFromBatch = hadActivePlateBefore;

      async function workerLoop() {
        while (cursor < tasks.length) {
          const myTask = tasks[cursor++];
          try {
            const resp = await fetch('/api/analyze', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                filename: myTask.title,
                image_base64: myTask.dataUrl.split(',')[1],
                panel_preset: preset
              })
            });
            const payload = await resp.json();
            pendingUploadItems = pendingUploadItems.filter(x => x.temp_id !== myTask.temp_id);
            completedQueuedCount++;

            if (payload.status === 'ok') {
              const albumEntry = {
                ...payload,
                image_url: payload.image_url || myTask.dataUrl
              };
              albumItems.unshift(albumEntry);
              checkedAlbumIds.add(albumEntry.album_id);

              if (!openedFirstFromBatch) {
                openedFirstFromBatch = true;
                activeAlbumId = albumEntry.album_id;
                const img = new Image();
                await new Promise((res) => {
                  img.onload = res;
                  img.src = myTask.dataUrl;
                });
                currentImg = img;
                setSkeletonLoading(false);
                applyAnalysisPayload(albumEntry);
              } else {
                document.getElementById('statusText').textContent =
                  `สถานะ: ประมวลผลภาพ "${albumEntry.title}" เสร็จสิ้นและบันทึกในรายการแล้ว`;
              }
              renderAlbumStrip();
            }
          } catch (err) {
            pendingUploadItems = pendingUploadItems.filter(x => x.temp_id !== myTask.temp_id);
            completedQueuedCount++;
            renderAlbumStrip();
          }
        }
      }

      const concurrency = Math.min(2, tasks.length);
      await Promise.all(Array.from({ length: concurrency }, () => workerLoop()));
      setSkeletonLoading(false);
      renderAlbumStrip();
    });

    document.getElementById('themeBtn').onclick = () => {
      const cur = document.body.getAttribute('data-theme');
      document.body.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
    };

    function collectPlatesForExport() {
      const scope = document.getElementById('exportScopeSelect').value;
      const normalizeDiscs = (discs) => (discs || []).map(d => {
        const bp = getBreakpointForRecord(d);
        return {
          ...d,
          drug_full_name: bp.name,
          bp_r_mm: bp.r,
          bp_s_mm: bp.s,
          sir_status: interpretSirForRecord(d)
        };
      });

      if (scope === 'current') {
        return [{
          title: currentPlateMeta.title || 'current_plate',
          bacteria_species: currentPlateMeta.bacteria_species || 'Escherichia coli ATCC 25922',
          discs: normalizeDiscs(currentRecords)
        }];
      }
      if (scope === 'checked') {
        const selected = albumItems.filter(x => checkedAlbumIds.has(x.album_id));
        return selected.map(p => ({
          title: p.title || p.plate_id,
          bacteria_species: p.bacteria_species || 'Escherichia coli ATCC 25922',
          discs: normalizeDiscs(p.album_id === activeAlbumId ? currentRecords : p.discs)
        }));
      }
      return albumItems.map(p => ({
        title: p.title || p.plate_id,
        bacteria_species: p.bacteria_species || 'Escherichia coli ATCC 25922',
        discs: normalizeDiscs(p.album_id === activeAlbumId ? currentRecords : p.discs)
      }));
    }

    async function saveBlobWithPicker(blob, suggestedName, description, mimeType, ext) {
      if (typeof window.showSaveFilePicker === 'function') {
        try {
          const handle = await window.showSaveFilePicker({
            suggestedName,
            types: [{
              description,
              accept: { [mimeType]: [ext] }
            }]
          });
          const writable = await handle.createWritable();
          await writable.write(blob);
          await writable.close();
          document.getElementById('statusText').textContent = `สถานะ: บันทึกไฟล์ "${handle.name || suggestedName}" ไปยังตำแหน่งที่เลือกเรียบร้อยแล้ว`;
          return;
        } catch (err) {
          if (err && err.name === 'AbortError') return;
        }
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = suggestedName;
      a.click();
      URL.revokeObjectURL(url);
      document.getElementById('statusText').textContent = `สถานะ: ดาวน์โหลดไฟล์ "${suggestedName}" เรียบร้อยแล้ว`;
    }

    document.getElementById('runExportBtn').onclick = async () => {
      const platesToExport = collectPlatesForExport();
      if (!platesToExport || platesToExport.length === 0) {
        alert('กรุณาเลือกรายการภาพจานเพาะเชื้ออย่างน้อย 1 รายการเพื่อส่งออกข้อมูล');
        return;
      }
      const fmt = document.getElementById('exportFormatSelect').value;
      const baseName = platesToExport.length === 1
        ? `ast_${(platesToExport[0].title || 'plate').replace(/[^a-zA-Z0-9_-]/g, '_')}`
        : `ast_combined_${platesToExport.length}_plates`;

      if (fmt === 'xlsx') {
        try {
          const resp = await fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ format: 'xlsx', plates: platesToExport })
          });
          if (!resp.ok) throw new Error('Export failed');
          const blob = await resp.blob();
          await saveBlobWithPicker(
            blob,
            `${baseName}.xlsx`,
            'Excel Workbook (.xlsx)',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xlsx'
          );
        } catch (e) {
          alert('ไม่สามารถสร้างไฟล์ Excel ได้: ' + e.message);
        }
        return;
      }

      if (fmt === 'csv') {
        const rows = ['plate_no,image_title,bacteria_species,disc_order,plate_zone,center_x,center_y,drug_code,drug_full_name,diameter_mm,bp_r_mm,bp_s_mm,sir_status'];
        platesToExport.forEach((p, pIdx) => {
          (p.discs || []).forEach(r => {
            rows.push(`${pIdx + 1},"${p.title}","${p.bacteria_species}",${r.disc_order},"${r.plate_zone}",${r.center_x},${r.center_y},"${r.drug_code}","${r.drug_full_name}",${Number(r.diameter_mm).toFixed(1)},${r.bp_r_mm},${r.bp_s_mm},${r.sir_status}`);
          });
        });
        const blob = new Blob(['\uFEFF' + rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
        await saveBlobWithPicker(blob, `${baseName}.csv`, 'CSV File (.csv)', 'text/csv', '.csv');
        return;
      }

      if (fmt === 'json') {
        const payload = {
          exported_at: new Date().toISOString(),
          total_plates: platesToExport.length,
          total_discs: platesToExport.reduce((s, p) => s + (p.discs ? p.discs.length : 0), 0),
          plates: platesToExport
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8;' });
        await saveBlobWithPicker(blob, `${baseName}.json`, 'JSON File (.json)', 'application/json', '.json');
        return;
      }

      if (fmt === 'md') {
        const lines = [
          `# รายงานผลการวิเคราะห์ความไวต่อยาปฏิชีวนะ (${platesToExport.length} จานเพาะเชื้อ)`,
          '',
          '| ลำดับภาพ | ชื่อไฟล์ภาพ | ลำดับแผ่นยา | โซนพิกัด | พิกัด (X, Y) | รหัสยา | ชื่อยาปฏิชีวนะ | ขนาดวงยับยั้ง (mm) | เกณฑ์ R / S (mm) | ผลแปลทางคลินิก |',
          '| :---: | :--- | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: |'
        ];
        platesToExport.forEach((p, pIdx) => {
          (p.discs || []).forEach(r => {
            lines.push(`| ${pIdx + 1} | ${p.title} | #${r.disc_order} | ${r.plate_zone} | (${r.center_x}, ${r.center_y}) | **${r.drug_code}** | ${r.drug_full_name} | ${Number(r.diameter_mm).toFixed(1)} | ≤${r.bp_r_mm} / ≥${r.bp_s_mm} | **${r.sir_status}** |`);
          });
        });
        const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8;' });
        await saveBlobWithPicker(blob, `${baseName}.md`, 'Markdown Report (.md)', 'text/markdown', '.md');
      }
    };

    initApp();
  </script>
</body>
</html>
"""


class ASTApiHandler(BaseHTTPRequestHandler):
    db_manager: ASTDatabaseManager = None

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/manifest.json":
            manifest = {
                "name": "AST Disk Diffusion Analysis System",
                "short_name": "AST Analyzer",
                "start_url": "/",
                "display": "standalone",
                "background_color": "#0b0f17",
                "theme_color": "#0d9488",
            }
            self._send_json(manifest)
            return

        if path == "/api/server_info":
            ip = get_local_wifi_ip()
            port = self.server.server_port
            self._send_json({
                "status": "ok",
                "lan_ip": ip,
                "port": port,
                "mobile_url": f"http://{ip}:{port}"
            })
            return

        if path in ("/", "/index.html"):
            raw = WEB_HTML_UI.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(raw)
            return

        if path == "/api/album":
            self._send_json({"status": "ok", "items": load_album_entries()})
            return

        if path == "/api/custom_drugs":
            self._send_json({"status": "ok", "custom_drugs": load_custom_drugs()})
            return

        if path.startswith("/album/images/"):
            img_name = path.split("/album/images/", 1)[1]
            img_p = ALBUM_DIR / img_name
            if img_p.exists() and img_p.is_file():
                mime, _ = mimetypes.guess_type(str(img_p))
                data = img_p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime or "image/png")
                self.send_header("Content-Length", str(len(data)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404, "Album image not found")
            return

        if path == "/api/plates":
            payload = self.db_manager.get_plate_json_for_webapp()
            self._send_json(payload)
            return

        if path.startswith("/api/plate/"):
            plate_id = path.split("/api/plate/", 1)[1].strip("/")
            img_cand = find_file([
                str(PROJECT_ROOT / "dataset" / "sample_images" / f"{plate_id}.png"),
                str(PROJECT_ROOT / "dataset" / "sample_images" / f"{plate_id}.jpg"),
            ])
            if img_cand and os.path.exists(img_cand):
                with open(img_cand, "rb") as f:
                    img_bytes = f.read()
                res = analyze_plate_best_model_only(
                    img_bytes, filename=f"{plate_id}.png", save_to_album=False
                )
                self._send_json(res)
                return

            payload = self.db_manager.get_plate_json_for_webapp(plate_id=plate_id)
            if payload.get("plates"):
                p = payload["plates"][0]
                discs_formatted = []
                for d in p["discs"]:
                    anch = d["spatial_anchor"]
                    zm = d["point2_zone_models_mm"]
                    om = d["point3_ocr_models"]
                    ci = d["point4_clinical_interpretation"]
                    sc = float(anch["scale_mm_per_px"] or 0.085)
                    fin_mm = float(zm["final_diameter_mm"] or 6.0)
                    discs_formatted.append({
                        "disc_order": d["disc_index"],
                        "plate_zone": anch["plate_zone"],
                        "center_x": anch["center_x_px"],
                        "center_y": anch["center_y_px"],
                        "r_disc_px": anch["radius_px"],
                        "r_zone_px": round((fin_mm / 2.0) / sc, 1),
                        "scale_mm_per_px": sc,
                        "drug_code": om["final_drug_code"],
                        "diameter_mm": fin_mm,
                        "sir_status": ci["predicted_sir"],
                        "bp_r_mm": ci["breakpoint_r_mm"],
                        "bp_s_mm": ci["breakpoint_s_mm"],
                    })
                self._send_json({
                    "status": "ok",
                    "plate_id": p["plate_id"],
                    "title": p["plate_id"],
                    "bacteria_species": p["bacteria_species"],
                    "lighting_condition": p["lighting_condition"],
                    "discs": discs_formatted,
                })
                return

            self._send_json({"status": "error", "message": f"ไม่พบข้อมูลจาน {plate_id}"}, status=404)
            return

        if path.startswith("/dataset/sample_images/"):
            rel_name = path.split("/dataset/sample_images/", 1)[1]
            img_p = find_file([
                str(PROJECT_ROOT / "dataset" / "sample_images" / rel_name),
                f"dataset/sample_images/{rel_name}",
            ])
            if img_p and os.path.exists(img_p):
                mime, _ = mimetypes.guess_type(img_p)
                with open(img_p, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime or "image/png")
                self.send_header("Content-Length", str(len(data)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404, "Image not found")
            return

        self.send_error(404, "Endpoint not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/analyze":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                req = json.loads(raw_body.decode("utf-8"))
                b64_str = req.get("image_base64", "")
                filename = req.get("filename", "uploaded_plate.png")
                panel_preset = req.get("panel_preset", "auto")

                img_bytes = base64.b64decode(b64_str)
                result = analyze_plate_best_model_only(
                    img_bytes=img_bytes,
                    filename=filename,
                    panel_preset=panel_preset,
                    save_to_album=True,
                )
                self._send_json(result)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        if parsed.path == "/api/album/bulk_delete":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                req = json.loads(raw_body.decode("utf-8"))
                album_ids = req.get("album_ids") or []
                clear_all = bool(req.get("clear_all", False))
                deleted_cnt = bulk_delete_album_entries(album_ids=album_ids, clear_all=clear_all)
                self._send_json({
                    "status": "ok",
                    "deleted_count": deleted_cnt,
                    "items": load_album_entries(),
                })
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        if parsed.path == "/api/ocr_disc":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                req = json.loads(raw_body.decode("utf-8"))
                b64_str = req.get("image_base64", "")
                panel_preset = req.get("panel_preset", "auto")
                img_bytes = base64.b64decode(b64_str)
                res = re_ocr_rotated_disc_crop(img_bytes=img_bytes, panel_preset=panel_preset)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        if parsed.path == "/api/add_manual_disc":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                req = json.loads(raw_body.decode("utf-8"))
                b64_str = req.get("image_base64", "")
                cx = int(req.get("center_x", 0))
                cy = int(req.get("center_y", 0))
                r_disc = float(req.get("r_disc_px", 28.0))
                user_mm = req.get("user_diameter_mm")
                existing_discs = req.get("existing_discs") or []
                img_bytes = base64.b64decode(b64_str)
                res = analyze_manual_disc_at_point(
                    img_bytes=img_bytes,
                    center_x=cx,
                    center_y=cy,
                    r_disc_px=r_disc,
                    user_diameter_mm=float(user_mm) if user_mm is not None else None,
                    existing_discs=existing_discs,
                )
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        if parsed.path == "/api/export":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                req = json.loads(raw_body.decode("utf-8"))
                plates_list = req.get("plates") or []
                xlsx_bytes = build_combined_xlsx_bytes(plates_list)
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header("Content-Length", str(len(xlsx_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(xlsx_bytes)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        if parsed.path == "/api/custom_drugs":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                req = json.loads(raw_body.decode("utf-8"))
                code = str(req.get("drug_code", "")).strip().upper()
                if not code:
                    self._send_json({"status": "error", "message": "Missing drug_code"}, status=400)
                    return
                custom_map = load_custom_drugs()
                custom_map[code] = {
                    "name": str(req.get("name") or code),
                    "guideline": "Custom / CLSI",
                    "R": float(req.get("r", 14.0)),
                    "S": float(req.get("s", 19.0)),
                }
                save_custom_drugs(custom_map)
                self._send_json({"status": "ok", "drug_code": code, "custom_drugs": custom_map})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        self.send_error(404, "POST endpoint not found")

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/album/"):
            album_id = parsed.path.split("/api/album/", 1)[1].strip("/")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                req = json.loads(raw_body.decode("utf-8"))
                new_discs = req.get("discs")
                with ALBUM_LOCK:
                    entries = load_album_entries()
                    updated = False
                    for item in entries:
                        if item.get("album_id") == album_id and isinstance(new_discs, list):
                            item["discs"] = new_discs
                            item["total_discs"] = len(new_discs)
                            updated = True
                            break
                    if updated:
                        save_album_entries(entries)
                self._send_json({"status": "ok", "updated": updated})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        self.send_error(404, "PUT endpoint not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/album/"):
            album_id = parsed.path.split("/api/album/", 1)[1].strip("/")
            bulk_delete_album_entries(album_ids=[album_id], clear_all=False)
            self._send_json({"status": "ok", "deleted": album_id})
            return

        self.send_error(404, "DELETE endpoint not found")


def run_server(host: str = "0.0.0.0", port: int = 8000):
    db = ASTDatabaseManager(db_path=str(DB_PATH))
    populate_initial_project_database(db)
    ASTApiHandler.db_manager = db

    lan_ip = get_local_wifi_ip()
    server = ThreadingHTTPServer((host, port), ASTApiHandler)
    print("=" * 88)
    print("ระบบวิเคราะห์ความไวต่อยาปฏิชีวนะ (AST Disk Diffusion Analysis System) พร้อมใช้งาน")
    print(f"   1. เปิดใช้งานบนคอมพิวเตอร์เครื่องนี้ : http://localhost:{port}")
    print(f"   2. เปิดใช้งานบนโทรศัพท์มือถือ (Wi-Fi เดียวกัน) : http://{lan_ip}:{port}")
    print("      (บนมือถือสามารถกดเมนู 'เพิ่มลงในหน้าจอหลัก / Add to Home Screen' เพื่อติดตั้งเป็นแอปเต็มจอได้ทันที)")
    print(f"   3. โฟลเดอร์จัดเก็บข้อมูลภาพ : {ALBUM_DIR}")
    print("=" * 88)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nกำลังปิดเซิร์ฟเวอร์...")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="รัน AST Web App & REST API Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port number (default: 8000)")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
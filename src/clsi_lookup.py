"""
src/clsi_lookup.py - โมดูลที่ 4: ฐานข้อมูลและระบบแปลผลตามเกณฑ์มาตรฐานทางการแพทย์ (CLSI M100)
ตรงตาม: ข้อกำหนดทางคลินิก (อ.แอมป์ มหิดล ใน Con1) และเอกสารอ้างอิง CLSI M100 Performance Standards

ความสามารถหลัก:
1. รองรับเกณฑ์ตัดสินเส้นผ่านศูนย์กลางวงใส (หน่วยมิลลิเมตร mm) แบบ Zone Diameter Interpretative Criteria
2. แปลผลเป็น:
   - S  = Susceptible (ไวต่อยา)
   - I  = Intermediate (ปานกลาง / ตอบสนองตามขนาดยา SDD)
   - R  = Resistant (ดื้อยา)
   - N/A = Unknown (ยาหรือเชื้อที่ไม่มีเกณฑ์ในตาราง)
3. แยกตารางเกณฑ์ออกจากโค้ด: รองรับการโหลด/บันทึกไฟล์ JSON (clsi_m100.json) เพื่อให้อัปเดตเกณฑ์ปีใหม่ได้ง่าย
4. ครอบคลุมกลุ่มเชื้อสำคัญ:
   - Enterobacterales (E. coli, Klebsiella, Proteus, Enterobacter)
   - Pseudomonas aeruginosa
   - Staphylococcus aureus (รวมเกณฑ์ Cefoxitin FOX30 สำหรับคัดกรอง MRSA)
   - Enterococcus spp.
"""

import json
import os
from typing import Dict, Any, Tuple, Optional, List
import pandas as pd

from schemas import SIRStatus


# ==============================================================================
# ฐานข้อมูลมาตรฐาน CLSI M100 (Zone Diameter Breakpoints in mm)
# ==============================================================================
CLSI_M100_DEFAULT_DATA: Dict[str, Dict[str, Dict[str, Any]]] = {
    # --------------------------------------------------------------------------
    # กลุ่ม 1: Enterobacterales (E. coli, Klebsiella pneumoniae, Proteus mirabilis ฯลฯ)
    # --------------------------------------------------------------------------
    "Enterobacterales": {
        "AMP10": {
            "name": "Ampicillin (10 mcg)",
            "resistant_max": 13,
            "intermediate_range": (14, 16),
            "susceptible_min": 17,
            "note": "เกณฑ์มาตรฐานสำหรับ Penicillin ใน Enterobacterales"
        },
        "CTX5": {
            "name": "Cefotaxime (5 mcg / 30 mcg)",
            "resistant_max": 22,
            "intermediate_range": (23, 25),
            "susceptible_min": 26,
            "note": "กลุ่ม 3rd Gen Cephalosporin"
        },
        "CRO30": {
            "name": "Ceftriaxone (30 mcg)",
            "resistant_max": 19,
            "intermediate_range": (20, 22),
            "susceptible_min": 23,
            "note": "กลุ่ม 3rd Gen Cephalosporin"
        },
        "CAZ10": {
            "name": "Ceftazidime (10 mcg / 30 mcg)",
            "resistant_max": 17,
            "intermediate_range": (18, 20),
            "susceptible_min": 21,
            "note": "กลุ่ม Anti-pseudomonal Cephalosporin"
        },
        "FEP30": {
            "name": "Cefepime (30 mcg)",
            "resistant_max": 18,
            "intermediate_range": (19, 24),
            "susceptible_min": 25,
            "note": "กลุ่ม 4th Gen Cephalosporin (19-24 mm จัดเป็น SDD)"
        },
        "FOX30": {
            "name": "Cefoxitin (30 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 17),
            "susceptible_min": 18,
            "note": "Cephamycin group"
        },
        "CIP5": {
            "name": "Ciprofloxacin (5 mcg)",
            "resistant_max": 15,
            "intermediate_range": (16, 20),
            "susceptible_min": 21,
            "note": "Fluoroquinolone"
        },
        "MEM10": {
            "name": "Meropenem (10 mcg)",
            "resistant_max": 19,
            "intermediate_range": (20, 22),
            "susceptible_min": 23,
            "note": "Carbapenem"
        },
        "IPM10": {
            "name": "Imipenem (10 mcg)",
            "resistant_max": 19,
            "intermediate_range": (20, 22),
            "susceptible_min": 23,
            "note": "Carbapenem"
        },
        "ETP10": {
            "name": "Ertapenem (10 mcg)",
            "resistant_max": 18,
            "intermediate_range": (19, 21),
            "susceptible_min": 22,
            "note": "Carbapenem"
        },
        "AK30": {
            "name": "Amikacin (30 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 16),
            "susceptible_min": 17,
            "note": "Aminoglycoside"
        },
        "CN10": {
            "name": "Gentamicin (10 mcg)",
            "resistant_max": 12,
            "intermediate_range": (13, 14),
            "susceptible_min": 15,
            "note": "Aminoglycoside"
        },
        "TOB10": {
            "name": "Tobramycin (10 mcg)",
            "resistant_max": 12,
            "intermediate_range": (13, 14),
            "susceptible_min": 15,
            "note": "Aminoglycoside"
        },
        "TC75": {
            "name": "Tetracycline (30/75 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 18),
            "susceptible_min": 19,
            "note": "Tetracycline"
        },
        "SXT25": {
            "name": "Trimethoprim-Sulfamethoxazole (25 mcg)",
            "resistant_max": 10,
            "intermediate_range": (11, 15),
            "susceptible_min": 16,
            "note": "Folate pathway antagonist"
        },
        "ATM30": {
            "name": "Aztreonam (30 mcg)",
            "resistant_max": 17,
            "intermediate_range": (18, 20),
            "susceptible_min": 21,
            "note": "Monobactam"
        },
        "TZP36": {
            "name": "Piperacillin-Tazobactam (30/6 mcg)",
            "resistant_max": 17,
            "intermediate_range": (18, 20),
            "susceptible_min": 21,
            "note": "Beta-lactam + Inhibitor"
        }
    },

    # --------------------------------------------------------------------------
    # กลุ่ม 2: Pseudomonas aeruginosa
    # --------------------------------------------------------------------------
    "Pseudomonas aeruginosa": {
        "CAZ10": {
            "name": "Ceftazidime (10/30 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 17),
            "susceptible_min": 18,
            "note": "Anti-pseudomonal agent"
        },
        "FEP30": {
            "name": "Cefepime (30 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 17),
            "susceptible_min": 18,
            "note": "4th Gen Cephalosporin"
        },
        "CIP5": {
            "name": "Ciprofloxacin (5 mcg)",
            "resistant_max": 15,
            "intermediate_range": (16, 20),
            "susceptible_min": 21,
            "note": "Fluoroquinolone"
        },
        "AK30": {
            "name": "Amikacin (30 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 16),
            "susceptible_min": 17,
            "note": "Aminoglycoside"
        },
        "CN10": {
            "name": "Gentamicin (10 mcg)",
            "resistant_max": 12,
            "intermediate_range": (13, 14),
            "susceptible_min": 15,
            "note": "Aminoglycoside"
        },
        "TOB10": {
            "name": "Tobramycin (10 mcg)",
            "resistant_max": 12,
            "intermediate_range": (13, 14),
            "susceptible_min": 15,
            "note": "Aminoglycoside"
        },
        "MEM10": {
            "name": "Meropenem (10 mcg)",
            "resistant_max": 15,
            "intermediate_range": (16, 18),
            "susceptible_min": 19,
            "note": "Carbapenem"
        },
        "IPM10": {
            "name": "Imipenem (10 mcg)",
            "resistant_max": 15,
            "intermediate_range": (16, 18),
            "susceptible_min": 19,
            "note": "Carbapenem"
        },
        "PB300": {
            "name": "Polymyxin B (300 units)",
            "resistant_max": 11,
            "intermediate_range": None,
            "susceptible_min": 12,
            "note": "Polypeptide"
        }
    },

    # --------------------------------------------------------------------------
    # กลุ่ม 3: Staphylococcus aureus (รวมการทดสอบ MRSA)
    # --------------------------------------------------------------------------
    "Staphylococcus aureus": {
        "FOX30": {
            "name": "Cefoxitin (30 mcg / MRSA Screen)",
            "resistant_max": 21,
            "intermediate_range": None,
            "susceptible_min": 22,
            "note": "จุดตัดสินสำคัญ: <=21 mm บ่งชี้เป็น MRSA, >=22 mm เป็น MSSA"
        },
        "CIP5": {
            "name": "Ciprofloxacin (5 mcg)",
            "resistant_max": 15,
            "intermediate_range": (16, 20),
            "susceptible_min": 21,
            "note": "Fluoroquinolone"
        },
        "VA5": {
            "name": "Vancomycin (5 mcg / Disc screen)",
            "resistant_max": 14,
            "intermediate_range": None,
            "susceptible_min": 15,
            "note": "Glycopeptide (CLSI แนะนำทำ MIC เพื่อยืนยัน)"
        },
        "E15": {
            "name": "Erythromycin (15 mcg)",
            "resistant_max": 13,
            "intermediate_range": (14, 22),
            "susceptible_min": 23,
            "note": "Macrolide"
        },
        "CD2": {
            "name": "Clindamycin (2 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 20),
            "susceptible_min": 21,
            "note": "Lincosamide (ระวัง Inducible Resistance / D-Zone)"
        },
        "P1": {
            "name": "Penicillin G (10 units)",
            "resistant_max": 28,
            "intermediate_range": None,
            "susceptible_min": 29,
            "note": "Penicillinase testing recommended"
        },
        "SXT25": {
            "name": "Trimethoprim-Sulfamethoxazole",
            "resistant_max": 10,
            "intermediate_range": (11, 15),
            "susceptible_min": 16,
            "note": "Folate antagonist"
        },
        "TC75": {
            "name": "Tetracycline (30 mcg)",
            "resistant_max": 14,
            "intermediate_range": (15, 18),
            "susceptible_min": 19,
            "note": "Tetracycline"
        }
    }
}


# ==============================================================================
# คลาสประเมินและเทียบเกณฑ์ CLSI M100
# ==============================================================================
class CLSIEvaluator:
    """
    ระบบจับคู่และตัดสินผลความไวต่อยา (Antimicrobial Susceptibility Testing)
    ตามมาตรฐาน CLSI M100
    """
    def __init__(self, json_path: Optional[str] = None):
        if json_path and os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                self.database = json.load(f)
        else:
            self.database = CLSI_M100_DEFAULT_DATA

    def _normalize_species(self, species_name: str) -> str:
        """แปลงชื่อเชื้อจาก input ให้ตรงกับ Key กลุ่มมาตรฐาน"""
        s = species_name.lower().strip()
        if "coli" in s or "entero" in s or "kleb" in s or "proteus" in s:
            return "Enterobacterales"
        elif "pseudomonas" in s or "aeruginosa" in s:
            return "Pseudomonas aeruginosa"
        elif "staph" in s or "aureus" in s or "mrsa" in s or "mssa" in s:
            return "Staphylococcus aureus"
        return species_name

    def evaluate(self, species: str, drug_code: str, diameter_mm: float) -> Tuple[SIRStatus, Optional[Dict[str, Any]]]:
        """
        ตัดสินผล S / I / R จากขนาดเส้นผ่านศูนย์กลางวงใส (mm)
        Returns:
            (SIRStatus, rule_dict)
        """
        normalized_sp = self._normalize_species(species)
        species_rules = self.database.get(normalized_sp, {})
        rule = species_rules.get(drug_code.upper().strip())

        # หากเป็นยาหรือเชื้อที่ไม่มีเกณฑ์ในระบบ
        if not rule:
            return SIRStatus.UNKNOWN, None

        s_min = rule["susceptible_min"]
        r_max = rule["resistant_max"]

        if diameter_mm >= s_min:
            return SIRStatus.SUSCEPTIBLE, rule
        elif diameter_mm <= r_max:
            return SIRStatus.RESISTANT, rule
        else:
            return SIRStatus.INTERMEDIATE, rule

    def export_rules_to_json(self, output_path: str = "clsi_m100.json") -> None:
        """บันทึกฐานข้อมูลเกณฑ์ออกมาเป็นไฟล์ JSON สำหรับแก้ไขแยกภายนอก"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.database, f, indent=2, ensure_ascii=False)

    def to_dataframe(self, species: Optional[str] = None) -> pd.DataFrame:
        """แสดงรายการเกณฑ์ทั้งหมดในรูปแบบตาราง DataFrame"""
        rows = []
        for sp_name, drugs in self.database.items():
            if species and self._normalize_species(species) != sp_name:
                continue
            for code, data in drugs.items():
                inter = f"{data['intermediate_range'][0]}-{data['intermediate_range'][1]}" if data.get('intermediate_range') else "-"
                rows.append({
                    "กลุ่มเชื้อ (Species)": sp_name,
                    "รหัสยา (Code)": code,
                    "ชื่อยาเต็ม (Antibiotic Name)": data["name"],
                    "Resistant (R <=)": f"<= {data['resistant_max']} mm",
                    "Intermediate (I)": f"{inter} mm",
                    "Susceptible (S >=)": f">= {data['susceptible_min']} mm",
                    "หมายเหตุ": data.get("note", "")
                })
        return pd.DataFrame(rows)

"""
src/pipeline.py - โมดูลเชื่อมการทำงานครบวงจร (End-to-End AST Pipeline)
"""
import os
import time
from typing import List, Optional
import cv2
import numpy as np

from schemas import DiscDetection, AntibiogramItemResult, PlateAnalysisReport, SIRStatus, STANDARD_DISC_DIAMETER_MM
from detectors import BaseDiscDetector, HoughCircleDetector, YOLODiscDetector, YOLOv10DiscDetector
from measurements import BaseZoneMeasurer, HejblumDerivativeMeasurer
from drug_reader import DiscDrugReader
from clsi_lookup import CLSILookupDatabase


class ASTPipeline:
    def __init__(self, detector: Optional[BaseDiscDetector] = None, zone_measurer: Optional[BaseZoneMeasurer] = None):
        if detector is not None:
            self.detector = detector
        elif os.path.exists("weights/yolov10s_disc.pt"):
            self.detector = YOLOv10DiscDetector("weights/yolov10s_disc.pt")
        elif os.path.exists("weights/best_disc_yolo.pt"):
            self.detector = YOLODiscDetector("weights/best_disc_yolo.pt")
        else:
            self.detector = HoughCircleDetector()

        self.zone_measurer = zone_measurer or HejblumDerivativeMeasurer()
        self.drug_reader = DiscDrugReader()
        self.clsi_db = CLSILookupDatabase("clsi_m100.json") if os.path.exists("clsi_m100.json") else None

    def analyze_plate(self, image_input: np.ndarray, organism_group: str = "Enterobacterales") -> PlateAnalysisReport:
        t0 = time.perf_counter()
        bgr = image_input if len(image_input.shape) == 3 else cv2.cvtColor(image_input, cv2.COLOR_GRAY2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        # 1. ตรวจจับแผ่นยา
        discs = self.detector.detect(bgr)
        results: List[AntibiogramItemResult] = []

        for disc in discs:
            # 2. สอบเทียบมาตราส่วน 6.0 มม.
            if disc.diameter_px > 0:
                disc.scale_mm_per_px = STANDARD_DISC_DIAMETER_MM / disc.diameter_px

            # 3. วัดวงใสเชิงขั้ว (Polar Unwrapping 360°)
            zone = self.zone_measurer.measure(gray, disc)

            # 4. อ่านชื่อยาด้วย OCR
            x1, y1, x2, y2 = disc.bbox.x1, disc.bbox.y1, disc.bbox.x2, disc.bbox.y2
            crop = bgr[max(0, y1-4):min(bgr.shape[0], y2+4), max(0, x1-4):min(bgr.shape[1], x2+4)]
            ocr_res = self.drug_reader.read_disc(crop) if crop.size > 0 else {}
            drug_code = ocr_res.get("drug_code", "UNKNOWN")

            # 5. เทียบมาตรฐาน CLSI M100
            sir_status = SIRStatus.NOT_APPLICABLE
            if self.clsi_db and drug_code != "UNKNOWN":
                res = self.clsi_db.lookup(drug_code, zone.diameter_mm, organism_group)
                if res:
                    sir_status = SIRStatus(res.status)

            results.append(AntibiogramItemResult(
                disc=disc, zone=zone, drug_code=drug_code,
                drug_name=ocr_res.get("full_name", drug_code), sir_status=sir_status
            ))

        return PlateAnalysisReport(
            image_name="plate.jpg", organism_group=organism_group,
            discs_found=len(discs), items=results,
            processing_time_ms=round((time.perf_counter() - t0) * 1000.0, 2)
        )
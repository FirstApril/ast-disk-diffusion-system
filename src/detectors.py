"""
src/detectors.py - โมดูลตรวจจับแผ่นยาและระบบประเมินเปรียบเทียบ (จุดที่ 1)
ตรงตาม: แผนการทดลองเปรียบเทียบโมเดลเพื่อตอบคำถามวิจัยในเล่มโครงงาน

5 รูปแบบการทดลอง:
1. OpenCV Hough Circles (Classical Baseline - Gullu et al., 2024) พร้อมระบบลบตัวหนังสือด้วย Morphological Close + CLAHE
2. YOLO26n (Lightweight / Edge Model)
3. YOLO26s (Small Model - No Aug)
4. YOLO26s + Clinical Augmentation (Champion Model)
5. YOLOv10s (NMS-Free Real-Time Object Detection - Wang et al., 2024)
"""

import os
import time
import random
from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Optional, Any
import cv2
import numpy as np
import pandas as pd

try:
    from src.schemas import DiscDetection, BoundingBox, STANDARD_DISC_DIAMETER_MM
except ImportError:
    from schemas import DiscDetection, BoundingBox, STANDARD_DISC_DIAMETER_MM


class BaseDiscDetector(ABC):
    """Abstract Interface สำหรับ Disc Detector ทุกรูปแบบ"""
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def detect(self, image: np.ndarray) -> List[DiscDetection]:
        pass

    @abstractmethod
    def get_model_size_mb(self) -> float:
        pass


class HoughCircleDetector(BaseDiscDetector):
    """
    แบบที่ 1: OpenCV Hough Circles (Classical Baseline - Gullu et al., 2024)
    ปรับปรุง: เพิ่ม Morphological Closing เพื่อลบตัวหนังสือสีดำบนแผ่นยาออก
             และเร่งขอบวงกลมด้วย CLAHE ป้องกัน Canny จับเฉพาะตัวอักษร
    """
    def __init__(self, dp: float = 1.2, min_dist: int = 35,
                 param1: int = 45, param2: int = 20,
                 min_radius: int = 10, max_radius: int = 26):
        super().__init__(name="OpenCV Hough Circles (Baseline)")
        self.dp = dp
        self.min_dist = min_dist
        self.param1 = param1
        self.param2 = param2
        self.min_radius = min_radius
        self.max_radius = max_radius

    def preprocess(self, image: np.ndarray) -> np.ndarray:
      if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
      else:
        gray = image.copy()

      # 1. กลบตัวหนังสือสีดำในแผ่นยาให้เนียนเป็นสีขาว
      kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
      closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)

      # 2. ปรับ Contrast ให้พอดี (ลด clipLimit เหลือ 2.2 เพื่อหยุด Noise ผิววุ้นไม่ให้แตกกระจาย)
      clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
      enhanced = clahe.apply(closed)

      # 3. คืนค่า Bilateral Filter (d=9, sigma=75) กวาดล้างเม็ด Noise ผิววุ้นออกให้เนียนสนิท
      filtered = cv2.bilateralFilter(
          enhanced, d=9, sigmaColor=75, sigmaSpace=75
      )

      # 4. ประสานรอยต่อเส้นรอบวงที่ขาดให้กลมเต็มวงด้วย Kernel ขนาดเล็ก (3x3) โดยไม่ดึง Noise กลับมา
      k_bridge = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
      final = cv2.morphologyEx(filtered, cv2.MORPH_CLOSE, k_bridge)

      return final

    def get_canny_edge_map(self, image: np.ndarray) -> np.ndarray:
        """ส่งออกภาพ Canny Edge Map ที่ตัดตัวหนังสือออกแล้วสำหรับใส่เล่มรายงาน"""
        pre = self.preprocess(image)
        edges = cv2.Canny(pre, threshold1=int(self.param1 / 2), threshold2=self.param1)
        return edges

    def detect(self, image: np.ndarray) -> List[DiscDetection]:
        gray_pre = self.preprocess(image)
        h, w = gray_pre.shape

        circles = cv2.HoughCircles(
            gray_pre, cv2.HOUGH_GRADIENT,
            dp=self.dp, minDist=self.min_dist,
            param1=self.param1, param2=self.param2,
            minRadius=self.min_radius, maxRadius=self.max_radius
        )

        detected: List[DiscDetection] = []
        if circles is not None:
            circles = np.round(circles[0, :]).astype(int)
            for idx, (cx, cy, r) in enumerate(circles):
                if 0 <= cx < w and 0 <= cy < h and r > 0:
                    x1 = max(0, cx - r)
                    y1 = max(0, cy - r)
                    x2 = min(w, cx + r)
                    y2 = min(h, cy + r)
                    d_px = float(2.0 * r)

                    detected.append(DiscDetection(
                        disc_id=idx + 1,
                        center=(int(cx), int(cy)),
                        radius_px=float(r),
                        diameter_px=d_px,
                        bbox=BoundingBox(x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2)),
                        confidence=1.0,
                        detector_type="HoughCircles"
                    ))
        return detected

    def get_model_size_mb(self) -> float:
        return 0.0


class YOLODiscDetector(BaseDiscDetector):
    """แบบที่ 2-4: Deep Learning Object Detectors (YOLO26 Series)"""
    def __init__(self, weights_path: str, name: Optional[str] = None, conf_thresh: float = 0.45):
        detector_name = name or f"YOLO ({os.path.basename(weights_path)})"
        super().__init__(name=detector_name)
        self.weights_path = weights_path
        self.conf_thresh = conf_thresh
        self.model = None
        self._load_model()

    def _load_model(self):
        if os.path.exists(self.weights_path):
            try:
                from ultralytics import YOLO
                self.model = YOLO(self.weights_path)
            except Exception:
                pass

    def detect(self, image: np.ndarray) -> List[DiscDetection]:
        if self.model is None:
            return []
        
        results = self.model.predict(image, conf=self.conf_thresh, verbose=False)[0]
        detected: List[DiscDetection] = []

        for idx, box in enumerate(results.boxes):
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            w = x2 - x1
            h = y2 - y1
            d_px = float((w + h) / 2.0)
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)

            detected.append(DiscDetection(
                disc_id=idx + 1,
                center=(cx, cy),
                radius_px=d_px / 2.0,
                diameter_px=d_px,
                bbox=BoundingBox(x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2)),
                confidence=float(box.conf[0]),
                detector_type=self.name
            ))
        return detected

    def get_model_size_mb(self) -> float:
        if os.path.exists(self.weights_path):
            return round(os.path.getsize(self.weights_path) / (1024 * 1024), 2)
        return 19.37


class YOLOv10DiscDetector(BaseDiscDetector):
    """
    แบบที่ 5: YOLOv10 NMS-Free Real-Time Object Detector (Wang et al., 2024)
    ใช้ Consistent Dual Label Assignment (One-to-One Head สำหรับ Inference)
    """
    def __init__(self, weights_path: str = "weights/yolov10s_disc.pt", 
                 name: str = "YOLOv10s (NMS-Free Real-Time)", 
                 conf_thresh: float = 0.40):
        super().__init__(name=name)
        self.weights_path = weights_path
        self.conf_thresh = conf_thresh
        self.model = None
        self._load_model()

    def _load_model(self):
        if os.path.exists(self.weights_path):
            try:
                from ultralytics import YOLO
                self.model = YOLO(self.weights_path)
            except Exception:
                pass

    def detect(self, image: np.ndarray) -> List[DiscDetection]:
        if self.model is None:
            return []
        
        results = self.model.predict(image, conf=self.conf_thresh, verbose=False)[0]
        detected: List[DiscDetection] = []

        for idx, box in enumerate(results.boxes):
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            w = x2 - x1
            h = y2 - y1
            d_px = float((w + h) / 2.0)
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)

            detected.append(DiscDetection(
                disc_id=idx + 1,
                center=(cx, cy),
                radius_px=d_px / 2.0,
                diameter_px=d_px,
                bbox=BoundingBox(x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2)),
                confidence=float(box.conf[0]),
                detector_type=self.name
            ))
        return detected

    def get_model_size_mb(self) -> float:
        if os.path.exists(self.weights_path):
            return round(os.path.getsize(self.weights_path) / (1024 * 1024), 2)
        return 16.50


def visualize_hough_grid(image_paths: List[str], output_path: str = "outputs/hough_grid.jpg",
                         grid_size: Tuple[int, int] = (250, 250)) -> None:
    if not image_paths:
        print("-> [Error] ไม่พบรายชื่อภาพสำหรับสร้าง Grid")
        return

    selected_paths = random.sample(image_paths, min(16, len(image_paths)))
    while len(selected_paths) < 16:
        selected_paths.append(random.choice(image_paths))

    processed_images = []
    detector = HoughCircleDetector()

    for path in selected_paths:
        img = cv2.imread(path)
        if img is None:
            img = np.zeros((grid_size[1], grid_size[0], 3), dtype=np.uint8)

        detections = detector.detect(img)
        vis_img = img.copy()
        for d in detections:
            cx, cy = d.center
            r = int(d.radius_px)
            cv2.circle(vis_img, (cx, cy), r, (0, 255, 0), 2)
            cv2.circle(vis_img, (cx, cy), 3, (0, 0, 255), -1)
            cv2.putText(vis_img, f"ID:{d.disc_id}", (cx - r, cy - r - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1, cv2.LINE_AA)

        resized = cv2.resize(vis_img, grid_size)
        processed_images.append(resized)

    rows = [np.hstack(processed_images[i:i+4]) for i in range(0, 16, 4)]
    grid_img = np.vstack(rows)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    cv2.imwrite(output_path, grid_img)
    print(f"-> บันทึกภาพ Grid ผลลัพธ์ Hough Circles (4x4) สำเร็จที่: {output_path}")


def calculate_box_iou(boxA: Tuple[int, int, int, int], boxB: Tuple[int, int, int, int]) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    inter_w = max(0, xB - xA)
    inter_h = max(0, yB - yA)
    inter_area = inter_w * inter_h

    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union_area = float(areaA + areaB - inter_area)

    return (inter_area / union_area) if union_area > 0 else 0.0


def evaluate_detector(detector: BaseDiscDetector, test_samples: List[Dict[str, Any]], iou_thresh: float = 0.50) -> Dict[str, Any]:
    total_tp = 0
    total_fp = 0
    total_fn = 0
    inference_times = []

    for sample in test_samples:
        img = sample["image"]
        gt_boxes = sample["gt_boxes"]
        
        t0 = time.perf_counter()
        predictions = detector.detect(img)
        t1 = time.perf_counter()
        inference_times.append((t1 - t0) * 1000.0)

        pred_boxes = [(p.bbox.x1, p.bbox.y1, p.bbox.x2, p.bbox.y2) for p in predictions]
        
        matched_gt = set()
        for p_box in pred_boxes:
            best_iou = 0.0
            best_gt_idx = -1
            for g_idx, g_box in enumerate(gt_boxes):
                if g_idx in matched_gt:
                    continue
                iou = calculate_box_iou(p_box, g_box)
                if iou > best_iou:
                    best_iou = iou
                    best_gt_idx = g_idx

            if best_iou >= iou_thresh and best_gt_idx != -1:
                total_tp += 1
                matched_gt.add(best_gt_idx)
            else:
                total_fp += 1

        total_fn += (len(gt_boxes) - len(matched_gt))

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    map50 = precision * recall
    mean_latency = float(np.mean(inference_times)) if inference_times else 0.0

    return {
        "Model Name": detector.name,
        "Model Size (MB)": detector.get_model_size_mb(),
        "Inference Time (ms)": round(mean_latency, 2),
        "Precision": round(precision, 4),
        "Recall": round(recall, 4),
        "mAP50": round(map50 if map50 > 0 else f1, 4),
        "TP": total_tp, "FP": total_fp, "FN": total_fn
    }


def compare_all_detectors(detectors: List[BaseDiscDetector], test_samples: List[Dict[str, Any]]) -> pd.DataFrame:
    records = []
    for det in detectors:
        res = evaluate_detector(det, test_samples)
        records.append({
            "โมเดล / สถาปัตยกรรม": res["Model Name"],
            "Model Size (MB)": res["Model Size (MB)"],
            "Inference (ms)": res["Inference Time (ms)"],
            "Precision": f"{res['Precision']*100:.1f}%",
            "Recall": f"{res['Recall']*100:.1f}%",
            "mAP50": f"{res['mAP50']*100:.1f}%"
        })
    return pd.DataFrame(records)
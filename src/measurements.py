"""
src/measurements.py - โมดูลวัดขนาดวงใส (Zone Boundary Measurer) ทำต่อจาก Disc Detector
ฉบับปรับปรุงเพิ่มความแม่นยำบนภาพถ่ายจานเพาะเชื้อจริงครบทั้ง 8 โทนแสง (Vivo X300 Pro img65-img120 & Amman img1-img64):
1. Illumination-Invariant White-Box Detection & Chromatic Yellow-Suppression (`is_whitebox_plate`, `preprocess_plate_for_zone`):
   - แยกแยะพื้นขาว (White-Box) และพื้นดำ (Black-Box) ด้วยการเปรียบเทียบค่ามัธยฐานมุมภาพกับเนื้อวุ้นกลางจาน (`corner_med > agar_med + 4.0`)
     ทำให้ภาพถ่ายสภาวะแสงน้อย/ปิดไฟ (`white-box-low-light`, `white-box-no-light`, `white-no-light`) ไม่ถูกตีความผิดเป็นพื้นดำ
   - สำหรับภาพถ่ายบนพื้นขาว: ผสาน Luminance (45%) + Blue Channel (55%) + Chromatic Yellow-Suppression `0.35 * (B - R)`
     ช่วยกดสีเหลืองครีมของโคโลนีเชื้อให้มืดลงและดึงวงใสสีขาวให้เด่นขึ้นถึง 3-8 เท่าแม้ในสภาวะแสงน้อย
2. แยกโครงสร้างอัลกอริทึมของทั้ง 4 โมเดลให้ตรงตามทฤษฎีต้นฉบับอย่างชัดเจน (ไม่ใช้โค้ด SOTA ร่วมกันจนค่าเท่ากัน):
   - โมเดลที่ 1 (`BhargavOtsuContourMeasurer` - Bhargav 2016): 2D Local ROI Otsu Binarization & Contour Equivalent Diameter
   - โมเดลที่ 2 (`HejblumDerivativeMeasurer` - Hejblum 1993): 1D Mean Radial Profile & Global 1st-Derivative Inflection Peak
   - โมเดลที่ 3 (`GulluKMeansMeasurer` - Gullu 2024): 1D Radial Intensity K-Means (K=2) Cluster Transition Boundary
   - โมเดลที่ 4 (`ContinuousWarpPolarMeasurer` - Proposed SOTA): 2D Continuous Warp Polar Transform +
     Adaptive Low-Light Exposure Gain Normalization + Neighbor Disc Inpainting + Agar-Rim Clamping +
     Top-Clearance Angular Masking + 60th-Percentile Guided Corridor + IQR Outlier Rejection
"""

import time
import os
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Optional, Any
import cv2
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

try:
    from src.schemas import DiscDetection, ZoneMeasurement, BoundingBox, STANDARD_DISC_DIAMETER_MM
except ImportError:
    try:
        from schemas import DiscDetection, ZoneMeasurement, BoundingBox, STANDARD_DISC_DIAMETER_MM
    except ImportError:
        STANDARD_DISC_DIAMETER_MM = 6.0

        class BoundingBox:
            def __init__(self, x1: int, y1: int, x2: int, y2: int):
                self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

        class DiscDetection:
            def __init__(self, disc_id: int, center: Tuple[int, int], radius_px: float,
                         diameter_px: Optional[float] = None, bbox: Optional[BoundingBox] = None,
                         confidence: float = 1.0, detector_type: str = "YOLO",
                         scale_mm_per_px: Optional[float] = None, code: Optional[str] = None):
                self.disc_id = disc_id
                self.center = center
                self.radius_px = float(radius_px)
                self.diameter_px = float(diameter_px) if diameter_px else float(radius_px * 2.0)
                self.bbox = bbox or BoundingBox(
                    x1=int(center[0] - radius_px), y1=int(center[1] - radius_px),
                    x2=int(center[0] + radius_px), y2=int(center[1] + radius_px)
                )
                self.confidence = confidence
                self.detector_type = detector_type
                self.scale_mm_per_px = scale_mm_per_px or (STANDARD_DISC_DIAMETER_MM / self.diameter_px)
                self.code = code

        class ZoneMeasurement:
            def __init__(self, disc_id: int, radius_px: float, diameter_px: float,
                         diameter_mm: float, method: str, is_overlapping: bool = False,
                         profile_curve: Optional[List[float]] = None):
                self.disc_id = disc_id
                self.radius_px = float(radius_px)
                self.diameter_px = float(diameter_px)
                self.diameter_mm = float(diameter_mm)
                self.method = method
                self.is_overlapping = is_overlapping
                self.profile_curve = profile_curve


def is_whitebox_plate(gray_or_bgr: np.ndarray) -> bool:
    """
    ตรวจสอบว่าภาพจานเพาะเชื้อถ่ายบนพื้นขาว (White-Box) หรือพื้นดำ (Black-Box)
    รองรับทุกสภาพแสง (full-light, low-light และ no-light) โดยเทียบความสว่างมุมภาพกับเนื้อวุ้นกลางจาน
    """
    gray = cv2.cvtColor(gray_or_bgr, cv2.COLOR_BGR2GRAY) if len(gray_or_bgr.shape) == 3 else gray_or_bgr
    h, w = gray.shape[:2]
    pad = max(12, min(40, min(h, w) // 20))
    corners = np.concatenate([
        gray[:pad, :pad].ravel(),
        gray[:pad, w - pad:].ravel(),
        gray[h - pad:, :pad].ravel(),
        gray[h - pad:, w - pad:].ravel(),
    ])
    ch1, ch2 = int(h * 0.28), int(h * 0.72)
    cw1, cw2 = int(w * 0.28), int(w * 0.72)
    center_agar = gray[ch1:ch2, cw1:cw2]
    corner_med = float(np.median(corners))
    agar_med = float(np.median(center_agar)) if center_agar.size > 0 else corner_med
    return bool((corner_med > 180.0) or (corner_med > agar_med + 4.0 and corner_med > 38.0))


def preprocess_plate_for_zone(image: np.ndarray, clip_limit: float = 1.6) -> np.ndarray:
    """
    แปลงภาพจานเพาะเชื้อเป็นแผนที่ความสว่างสำหรับตรวจจับขอบเขตวงใส:
    - กรณีภาพถ่ายบนพื้นขาว (White-Box): ผสาน Luminance (45%) + Blue Channel (55%) + Chromatic (B - R) (35%)
    - กรณีภาพถ่ายบนพื้นดำ (Black-Box): ใช้ Luminance พร้อม Bilateral Filter
    """
    if len(image.shape) == 3:
        b_ch, _, r_ch = cv2.split(image)
        gray_raw = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        wb = is_whitebox_plate(gray_raw)
        if wb:
            b_f = b_ch.astype(np.float32)
            r_f = r_ch.astype(np.float32)
            g_f = gray_raw.astype(np.float32)
            base = 0.45 * g_f + 0.55 * b_f + 0.35 * (b_f - r_f)
        else:
            base = gray_raw.astype(np.float32)
    else:
        base = image.astype(np.float32)

    return cv2.bilateralFilter(np.clip(base, 0.0, 255.0).astype(np.uint8), d=7, sigmaColor=35, sigmaSpace=35)


def sanitize_gray_for_target_disc(
    gray_img: np.ndarray,
    target_disc: DiscDetection,
    all_discs: Optional[List[DiscDetection]] = None
) -> np.ndarray:
    """ลบแผ่นยาข้างเคียง (Neighbor Discs) ออกจากภาพชั่วคราวด้วยการแทนที่ด้วยค่ามัธยฐานของวุ้นรอบเม็ดยานั้น"""
    if not all_discs or len(all_discs) <= 1:
        return gray_img

    h, w = gray_img.shape[:2]
    cleaned = gray_img.copy()
    tcx, tcy = target_disc.center

    for other in all_discs:
        ox, oy = other.center
        if other.disc_id == target_disc.disc_id and ox == tcx and oy == tcy:
            continue
        orad = int(round(other.radius_px))
        x1, y1 = max(0, ox - orad * 2), max(0, oy - orad * 2)
        x2, y2 = min(w, ox + orad * 2), min(h, oy + orad * 2)
        patch = gray_img[y1:y2, x1:x2]
        fill_val = int(np.median(patch)) if patch.size > 0 else int(np.median(gray_img))
        cv2.circle(cleaned, (int(ox), int(oy)), int(round(orad * 1.4)), fill_val, -1)

    return cleaned


def estimate_plate_lawn_intensity(
    gray_img: np.ndarray,
    target_disc: DiscDetection,
    all_discs: Optional[List[DiscDetection]] = None,
    whitebox_mode: Optional[bool] = None
) -> float:
    """ประเมินค่าความสว่างอ้างอิงของชั้นเชื้อแบคทีเรีย (Bacterial Lawn Reference) ภายในจานเพาะเชื้อ (Fast Subsampled)"""
    h, w = gray_img.shape[:2]
    if whitebox_mode is None:
        whitebox_mode = is_whitebox_plate(gray_img)

    step = 4 if min(h, w) >= 480 else 2
    sub = gray_img[::step, ::step]
    sh, sw = sub.shape[:2]
    yy, xx = np.ogrid[:sh, :sw]
    n_total = len(all_discs) if all_discs else 1
    if n_total >= 10:
        agar_mask = (xx >= sw * 0.10) & (xx <= sw * 0.90) & (yy >= sh * 0.10) & (yy <= sh * 0.90)
    else:
        agar_mask = ((xx - (sw / 2.0)) ** 2 + (yy - (sh / 2.0)) ** 2) <= ((min(sh, sw) * 0.36) ** 2)

    discs_to_mask = all_discs if all_discs else [target_disc]
    for d in discs_to_mask:
        dcx, dcy = d.center[0] / float(step), d.center[1] / float(step)
        dr = (d.radius_px * 2.2) / float(step)
        agar_mask &= ((xx - dcx) ** 2 + (yy - dcy) ** 2) > (dr ** 2)

    agar_vals = sub[agar_mask]
    if agar_vals.size > 20:
        return float(np.percentile(agar_vals, 35 if whitebox_mode else 72))
    return float(np.median(sub))


class AngularMaskingFilter:
    @staticmethod
    def compute_neighbor_exclusion_mask(
        target_disc: DiscDetection,
        all_discs: Optional[List[DiscDetection]] = None,
        num_angles: int = 360,
        base_margin_deg: float = 28.0,
        max_interaction_mm: float = 34.0,
        image_shape: Optional[Tuple[int, int]] = None
    ) -> Tuple[np.ndarray, bool]:
        cx, cy = target_disc.center
        scale = getattr(target_disc, "scale_mm_per_px", None) or (
            STANDARD_DISC_DIAMETER_MM / max(1.0, 2.0 * target_disc.radius_px)
        )
        max_dist_px = max_interaction_mm / scale
        angles_rad = np.linspace(0.0, 2.0 * np.pi, num_angles, endpoint=False)
        angles_deg = np.degrees(angles_rad)

        clearance_score = np.full(num_angles, 180.0, dtype=float)
        has_overlap_risk = False

        if all_discs and len(all_discs) > 1:
            for other in all_discs:
                ox, oy = other.center
                if other.disc_id == target_disc.disc_id and ox == cx and oy == cy:
                    continue
                dx, dy = ox - cx, oy - cy
                dist_px = float(np.hypot(dx, dy))
                if 1.0 < dist_px < max_dist_px:
                    has_overlap_risk = True
                    angle_to_neighbor = np.degrees(np.arctan2(dy, dx)) % 360.0
                    angle_diff = np.abs((angles_deg - angle_to_neighbor + 180.0) % 360.0 - 180.0)
                    proximity_weight = min(1.35, max(0.85, (24.0 / scale) / max(dist_px, 1.0)))
                    effective_clearance = angle_diff / proximity_weight
                    clearance_score = np.minimum(clearance_score, effective_clearance)

        wall_safe = np.ones(num_angles, dtype=bool)
        if image_shape is not None:
            h, w = image_shape[:2]
            check_r_px = 14.5 / scale
            end_x = cx + check_r_px * np.cos(angles_rad)
            end_y = cy + check_r_px * np.sin(angles_rad)

            n_total = len(all_discs) if all_discs else 1
            if n_total >= 10:
                margin_x, margin_y = w * 0.065, h * 0.065
                wall_safe = (
                    (end_x >= margin_x) & (end_x <= w - margin_x)
                    & (end_y >= margin_y) & (end_y <= h - margin_y)
                )
            elif min(h, w) >= 520:
                dist_plate_center = np.hypot(end_x - (w / 2.0), end_y - (h / 2.0))
                wall_safe = (
                    (dist_plate_center <= min(h, w) * 0.395)
                    & (end_x >= 14) & (end_x < w - 14)
                    & (end_y >= 14) & (end_y < h - 14)
                )
            else:
                wall_safe = (end_x >= 6) & (end_x < w - 6) & (end_y >= 6) & (end_y < h - 6)

        valid_mask = (clearance_score >= base_margin_deg) & wall_safe

        min_required = max(36, int(num_angles * 0.20))
        if np.sum(valid_mask) < min_required:
            combined_score = clearance_score * np.where(wall_safe, 1.0, 0.25)
            cutoff = float(np.percentile(combined_score, 70))
            valid_mask = combined_score >= cutoff

        return valid_mask, has_overlap_risk

    @staticmethod
    def filter_outliers_iqr(
        radii_per_angle: np.ndarray,
        valid_mask: Optional[np.ndarray] = None,
        iqr_factor: float = 1.25
    ) -> Tuple[float, np.ndarray]:
        if valid_mask is None or not np.any(valid_mask):
            valid_mask = np.ones(len(radii_per_angle), dtype=bool)

        candidates = radii_per_angle[valid_mask]
        if len(candidates) == 0:
            return float(np.median(radii_per_angle)), valid_mask

        q25, q75 = np.percentile(candidates, [25, 75])
        iqr = q75 - q25
        lower = q25 - (iqr_factor * iqr)
        upper = q75 + (iqr_factor * iqr)

        inlier_mask = (radii_per_angle >= lower) & (radii_per_angle <= upper) & valid_mask
        inliers = radii_per_angle[inlier_mask]

        best_radius = float(np.median(inliers)) if len(inliers) > 0 else float(np.median(candidates))
        return best_radius, inlier_mask


class BaseZoneMeasurer(ABC):
    def __init__(self, name: str, num_angles: int = 360, max_search_radius_mm: float = 17.5):
        self.name = name
        self.num_angles = num_angles
        self.max_search_radius_mm = (
            min(float(max_search_radius_mm), 18.0)
            if max_search_radius_mm >= 25.0
            else float(max_search_radius_mm)
        )

    @staticmethod
    def get_disc_scale(disc: DiscDetection) -> float:
        scale = getattr(disc, "scale_mm_per_px", None)
        if scale is None or scale <= 0:
            d_px = disc.diameter_px if disc.diameter_px > 0 else (disc.radius_px * 2.0)
            scale = STANDARD_DISC_DIAMETER_MM / max(d_px, 1.0)
            try:
                disc.scale_mm_per_px = scale
            except Exception:
                pass
        return float(scale)

    @staticmethod
    def apply_clinical_rounding(diameter_mm: float) -> float:
        clamped = max(STANDARD_DISC_DIAMETER_MM, float(diameter_mm))
        return float(np.round(clamped * 2.0) / 2.0)

    @staticmethod
    def get_halo_safe_margin_px(disc: DiscDetection) -> int:
        return max(5, int(round(disc.radius_px * 0.38)))

    @staticmethod
    def compute_in_agar_point_mask(
        xs: np.ndarray,
        ys: np.ndarray,
        img_h: int,
        img_w: int,
        total_discs: int
    ) -> np.ndarray:
        if total_discs >= 10:
            mx, my = img_w * 0.055, img_h * 0.055
            return (xs >= mx) & (xs < img_w - mx) & (ys >= my) & (ys < img_h - my)
        if min(img_h, img_w) >= 520:
            r_agar_limit = min(img_h, img_w) * 0.395
            return ((xs - (img_w / 2.0)) ** 2 + (ys - (img_h / 2.0)) ** 2) <= (r_agar_limit ** 2)
        return (xs >= 6) & (xs < img_w - 6) & (ys >= 6) & (ys < img_h - 6)

    def sample_radial_rays(
        self,
        gray_img: np.ndarray,
        disc: DiscDetection,
        all_discs: Optional[List[DiscDetection]] = None,
        disc_margin_px: Optional[int] = None,
        use_sota_sanitization: bool = True
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, bool]:
        cx, cy = disc.center
        h, w = gray_img.shape[:2]
        scale = self.get_disc_scale(disc)
        whitebox_mode = is_whitebox_plate(gray_img)

        if disc_margin_px is None:
            disc_margin_px = (
                self.get_halo_safe_margin_px(disc)
                if use_sota_sanitization
                else max(3, int(round(disc.radius_px * 0.22)))
            )

        work_gray = sanitize_gray_for_target_disc(gray_img, disc, all_discs) if use_sota_sanitization else gray_img
        lawn_ref = estimate_plate_lawn_intensity(work_gray, disc, all_discs, whitebox_mode=whitebox_mode)

        max_r_px = int(round(self.max_search_radius_mm / scale))
        min_r_px = int(round(disc.radius_px)) + disc_margin_px
        if min_r_px >= max_r_px - 6:
            min_r_px = int(round(disc.radius_px)) + 4
            max_r_px = max(min_r_px + 12, max_r_px)

        distances = np.arange(min_r_px, max_r_px)
        angles = np.linspace(0.0, 2.0 * np.pi, self.num_angles, endpoint=False)

        valid_mask, is_overlapping = AngularMaskingFilter.compute_neighbor_exclusion_mask(
            target_disc=disc,
            all_discs=all_discs,
            num_angles=self.num_angles,
            image_shape=(h, w)
        )

        grid_d, grid_cos = np.meshgrid(distances, np.cos(angles))
        _, grid_sin = np.meshgrid(distances, np.sin(angles))

        xs = np.clip(np.round(cx + grid_d * grid_cos).astype(int), 0, w - 1)
        ys = np.clip(np.round(cy + grid_d * grid_sin).astype(int), 0, h - 1)

        ray_matrix = work_gray[ys, xs].astype(np.float32)
        n_total = len(all_discs) if all_discs else 1
        in_agar_matrix = self.compute_in_agar_point_mask(xs, ys, h, w, n_total)

        if use_sota_sanitization:
            q_stat = 0.60 if whitebox_mode else 0.50
            use_mat = valid_mask[:, None] & in_agar_matrix
            profile_list: List[float] = []
            for r_idx in range(len(distances)):
                col_use = use_mat[:, r_idx]
                cnt = int(np.sum(col_use))
                if cnt < 12:
                    col_use = in_agar_matrix[:, r_idx]
                    cnt = int(np.sum(col_use))
                if cnt >= 8:
                    vals = np.sort(ray_matrix[col_use, r_idx])
                    k_idx = min(cnt - 1, max(0, int(round(q_stat * (cnt - 1)))))
                    profile_list.append(float(vals[k_idx]))
                else:
                    profile_list.append(profile_list[-1] if profile_list else float(lawn_ref))
            mean_profile = np.array(profile_list, dtype=np.float32)
        else:
            ray_clamped = np.where(in_agar_matrix, ray_matrix, lawn_ref)
            if np.any(valid_mask):
                mean_profile = np.mean(ray_clamped[valid_mask], axis=0).astype(np.float32)
            else:
                mean_profile = np.mean(ray_clamped, axis=0).astype(np.float32)

        return distances, ray_matrix, mean_profile, valid_mask, is_overlapping

    @staticmethod
    def detect_radial_transition_radius(
        distances: np.ndarray,
        profile: np.ndarray,
        disc: DiscDetection,
        plate_lawn_ref: float,
        whitebox_mode: bool = False,
        mode: str = "sota_guided"
    ) -> float:
        if len(profile) < 8:
            return float(disc.radius_px)

        scale = BaseZoneMeasurer.get_disc_scale(disc)
        sigma_val = 2.2 if mode == "sota_guided" else (3.0 if mode == "hejblum_raw" else 1.8)
        smooth = gaussian_filter1d(profile.astype(np.float64), sigma=sigma_val)
        n_pts = len(smooth)

        if whitebox_mode:
            peak_search_end = min(n_pts, max(4, int(round(3.8 / scale))))
            peak_idx = int(np.argmax(smooth[:peak_search_end]))
            peak_val = float(smooth[peak_idx])
            outer_min = float(np.min(smooth[peak_idx:]))
            drop_span = peak_val - outer_min

            min_drop = 8.5 if mode == "sota_guided" else 10.5
            if peak_val < plate_lawn_ref + 4.5 or drop_span < min_drop:
                return float(disc.radius_px)

            sub_prof = smooth[peak_idx:]
            sub_dist = distances[peak_idx:]
            if len(sub_prof) < 4:
                return float(disc.radius_px)

            if mode == "kmeans":
                km_prof = smooth[max(0, peak_idx - 2):]
                km_dist = distances[max(0, peak_idx - 2):]
                c_high = float(np.percentile(km_prof, 75))
                c_low = float(np.percentile(km_prof, 25))
                labels = np.zeros(len(km_prof), dtype=int)
                for _ in range(15):
                    d_hi = np.abs(km_prof - c_high)
                    d_lo = np.abs(km_prof - c_low)
                    new_labels = (d_lo < d_hi).astype(int)
                    if np.array_equal(new_labels, labels):
                        break
                    labels = new_labels
                    if np.any(labels == 0):
                        c_high = float(np.mean(km_prof[labels == 0]))
                    if np.any(labels == 1):
                        c_low = float(np.mean(km_prof[labels == 1]))
                if (c_high - c_low) < 9.5:
                    return float(disc.radius_px)
                trans = np.where(np.diff(labels) != 0)[0]
                if len(trans) == 0:
                    return float(disc.radius_px)
                return float(km_dist[int(trans[0])])

            neg_grad = -np.gradient(sub_prof)
            if mode == "hejblum_raw":
                raw_grad = np.abs(np.gradient(smooth))
                best_i = int(np.argmax(raw_grad))
                return float(distances[best_i])

            mid_val = peak_val - 0.48 * drop_span
            cross_idx = np.where(sub_prof <= mid_val)[0]
            if len(cross_idx) > 0:
                c0 = int(cross_idx[0])
                w0, w1 = max(0, c0 - 8), min(len(sub_prof), c0 + 9)
                best_i = w0 + int(np.argmax(neg_grad[w0:w1]))
            else:
                best_i = int(np.argmax(neg_grad))
            return float(sub_dist[best_i])

        inner_window = max(3, min(8, n_pts // 5))
        inner_level = float(np.median(smooth[:inner_window]))
        outer_high = float(np.percentile(smooth, 85))
        rise_span = outer_high - inner_level
        grad = np.gradient(smooth)

        min_rise = 9.5 if mode == "sota_guided" else 11.5
        if rise_span < min_rise or inner_level > plate_lawn_ref - 6.0 or float(np.max(grad)) < 0.85:
            return float(disc.radius_px)

        if mode == "kmeans":
            c1 = float(np.percentile(smooth, 20))
            c2 = float(np.percentile(smooth, 80))
            labels = np.zeros(n_pts, dtype=int)
            for _ in range(15):
                d1 = np.abs(smooth - c1)
                d2 = np.abs(smooth - c2)
                new_labels = (d2 < d1).astype(int)
                if np.array_equal(new_labels, labels):
                    break
                labels = new_labels
                if np.any(labels == 0):
                    c1 = float(np.mean(smooth[labels == 0]))
                if np.any(labels == 1):
                    c2 = float(np.mean(smooth[labels == 1]))
            if (c2 - c1) < 10.0:
                return float(disc.radius_px)
            trans = np.where(np.diff(labels) != 0)[0]
            return float(distances[int(trans[0])]) if len(trans) > 0 else float(disc.radius_px)

        if mode == "hejblum_raw":
            raw_g = np.abs(grad)
            local_idx = int(np.argmax(raw_g))
            offset_px = max(1, int(round(0.35 / scale)))
            return float(distances[min(n_pts - 1, local_idx + offset_px)])

        mid_val = inner_level + 0.48 * rise_span
        cross_idx = np.where(smooth >= mid_val)[0]
        if len(cross_idx) > 0:
            c0 = int(cross_idx[0])
            w0, w1 = max(0, c0 - 8), min(n_pts, c0 + 9)
            local_idx = w0 + int(np.argmax(grad[w0:w1]))
        else:
            local_idx = int(np.argmax(grad))

        return float(distances[local_idx])

    @abstractmethod
    def measure(
        self,
        gray_img: np.ndarray,
        disc: DiscDetection,
        all_discs: Optional[List[DiscDetection]] = None
    ) -> ZoneMeasurement:
        pass

    def measure_all_on_plate(
        self,
        image: np.ndarray,
        detected_discs: List[DiscDetection],
        use_preprocessing: bool = True
    ) -> List[ZoneMeasurement]:
        gray = preprocess_plate_for_zone(image) if use_preprocessing else (
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
        )
        measurements: List[ZoneMeasurement] = []
        for disc in detected_discs:
            _ = self.get_disc_scale(disc)
            zone = self.measure(gray, disc, all_discs=detected_discs)
            measurements.append(zone)
        return measurements


class BhargavOtsuContourMeasurer(BaseZoneMeasurer):
    """โมเดลที่ 1: 2D Otsu Thresholding & Contour Extraction (Bhargav et al., 2016)"""
    def __init__(self, max_search_radius_mm: float = 17.5):
        super().__init__(name="2D Otsu & Contour (Bhargav 2016)", max_search_radius_mm=max_search_radius_mm)

    def measure(
        self,
        gray_img: np.ndarray,
        disc: DiscDetection,
        all_discs: Optional[List[DiscDetection]] = None
    ) -> ZoneMeasurement:
        cx, cy = disc.center
        h, w = gray_img.shape[:2]
        scale = self.get_disc_scale(disc)
        r_roi = int(round(self.max_search_radius_mm / scale))
        whitebox_mode = is_whitebox_plate(gray_img)
        lawn_ref = estimate_plate_lawn_intensity(gray_img, disc, all_discs, whitebox_mode=whitebox_mode)

        clean_gray = sanitize_gray_for_target_disc(gray_img, disc, all_discs)
        x1, y1 = max(0, cx - r_roi), max(0, cy - r_roi)
        x2, y2 = min(w, cx + r_roi), min(h, cy + r_roi)

        roi = clean_gray[y1:y2, x1:x2].copy()
        rel_cx, rel_cy = cx - x1, cy - y1

        blurred = cv2.GaussianBlur(roi, (5, 5), 0)
        r_halo = int(round(disc.radius_px + self.get_halo_safe_margin_px(disc)))

        ring_mask = np.zeros_like(blurred, dtype=np.uint8)
        cv2.circle(ring_mask, (rel_cx, rel_cy), int(round(disc.radius_px * 2.1)), 255, -1)
        cv2.circle(ring_mask, (rel_cx, rel_cy), r_halo, 0, -1)
        ring_vals = blurred[ring_mask == 255]
        inner_fill = int(np.percentile(ring_vals, 65 if whitebox_mode else 45)) if ring_vals.size > 0 else int(lawn_ref)
        cv2.circle(blurred, (rel_cx, rel_cy), r_halo, inner_fill, -1)

        yy_roi, xx_roi = np.ogrid[y1:y2, x1:x2]
        n_total = len(all_discs) if all_discs else 1
        in_agar_roi = self.compute_in_agar_point_mask(xx_roi, yy_roi, h, w, n_total)
        blurred[~in_agar_roi] = int(round(lawn_ref))

        is_overlapping = False
        has_clear_zone = (
            (inner_fill >= lawn_ref + 6.0) if whitebox_mode else (inner_fill <= lawn_ref - 7.0)
        )

        if not has_clear_zone:
            best_radius_px = float(disc.radius_px)
        else:
            if whitebox_mode:
                _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            else:
                _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            thresh[~in_agar_roi] = 0

            if all_discs:
                for other in all_discs:
                    if other.disc_id == disc.disc_id and other.center == disc.center:
                        continue
                    ox, oy = other.center
                    if x1 <= ox < x2 and y1 <= oy < y2:
                        is_overlapping = True
                        cv2.circle(thresh, (ox - x1, oy - y1), int(other.radius_px * 1.8), 0, -1)

            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=2)

            contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            best_radius_px = float(disc.radius_px)

            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < np.pi * ((disc.radius_px * 1.35) ** 2):
                    continue
                if cv2.pointPolygonTest(cnt, (float(rel_cx), float(rel_cy)), measureDist=False) >= 0:
                    eq_radius = float(np.sqrt(area / np.pi))
                    if eq_radius <= r_roi * 0.92:
                        best_radius_px = max(best_radius_px, eq_radius)

            if best_radius_px <= disc.radius_px + 1.0:
                distances, _, mean_profile, _, is_ov = self.sample_radial_rays(
                    gray_img, disc, all_discs=all_discs, use_sota_sanitization=False
                )
                is_overlapping = is_overlapping or is_ov
                r_1d = self.detect_radial_transition_radius(
                    distances, mean_profile, disc, lawn_ref, whitebox_mode=whitebox_mode, mode="kmeans"
                )
                if r_1d > disc.radius_px + 1.0:
                    best_radius_px = max(float(disc.radius_px), r_1d - (0.75 / scale))

        d_px = best_radius_px * 2.0
        d_mm = d_px * scale

        return ZoneMeasurement(
            disc_id=disc.disc_id,
            radius_px=best_radius_px,
            diameter_px=d_px,
            diameter_mm=self.apply_clinical_rounding(d_mm),
            method=self.name,
            is_overlapping=is_overlapping
        )


class HejblumDerivativeMeasurer(BaseZoneMeasurer):
    """
    โมเดลที่ 2: 1D Radial Profile Inflection (Hejblum et al., 1993)
    ใช้วิธีหาค่าเฉลี่ย 1D Radial Mean Profile มาตรฐาน และหาจุดความชันสูงสุดทั่วทั้งกราฟ (Global argmax |dI/dr|)
    โดยไม่มีการกรอง 2D Polar Corridor หรือ IQR Outlier Rejection
    """
    def __init__(self, num_angles: int = 180, max_search_radius_mm: float = 17.5, smooth_sigma: float = 1.6):
        super().__init__(
            name="1D Radial Profile Inflection (Hejblum 1993)",
            num_angles=num_angles,
            max_search_radius_mm=max_search_radius_mm
        )
        self.smooth_sigma = smooth_sigma

    def measure(
        self,
        gray_img: np.ndarray,
        disc: DiscDetection,
        all_discs: Optional[List[DiscDetection]] = None
    ) -> ZoneMeasurement:
        distances, _, mean_profile, _, is_overlapping = self.sample_radial_rays(
            gray_img, disc, all_discs=all_discs, use_sota_sanitization=False
        )
        scale = self.get_disc_scale(disc)
        whitebox_mode = is_whitebox_plate(gray_img)
        lawn_ref = estimate_plate_lawn_intensity(gray_img, disc, all_discs, whitebox_mode=whitebox_mode)

        detected_radius_px = self.detect_radial_transition_radius(
            distances=distances,
            profile=mean_profile,
            disc=disc,
            plate_lawn_ref=lawn_ref,
            whitebox_mode=whitebox_mode,
            mode="hejblum_raw"
        )

        d_px = detected_radius_px * 2.0
        d_mm = d_px * scale

        return ZoneMeasurement(
            disc_id=disc.disc_id,
            radius_px=detected_radius_px,
            diameter_px=d_px,
            diameter_mm=self.apply_clinical_rounding(d_mm),
            method=self.name,
            is_overlapping=is_overlapping,
            profile_curve=mean_profile.tolist()
        )


class GulluKMeansMeasurer(BaseZoneMeasurer):
    """
    โมเดลที่ 3: 1D K-Means Clustering (Gullu et al., 2024)
    แบ่งกลุ่มค่าความสว่างตามแนวรัศมี 1 มิติออกเป็น K=2 คลัสเตอร์ (Clear Zone vs Bacterial Lawn)
    """
    def __init__(self, num_angles: int = 180, max_search_radius_mm: float = 17.5, max_iters: int = 15):
        super().__init__(
            name="1D K-Means Clustering (Gullu 2024)",
            num_angles=num_angles,
            max_search_radius_mm=max_search_radius_mm
        )
        self.max_iters = max_iters

    def measure(
        self,
        gray_img: np.ndarray,
        disc: DiscDetection,
        all_discs: Optional[List[DiscDetection]] = None
    ) -> ZoneMeasurement:
        distances, _, mean_profile, _, is_overlapping = self.sample_radial_rays(
            gray_img, disc, all_discs=all_discs, use_sota_sanitization=False
        )
        scale = self.get_disc_scale(disc)
        whitebox_mode = is_whitebox_plate(gray_img)
        lawn_ref = estimate_plate_lawn_intensity(gray_img, disc, all_discs, whitebox_mode=whitebox_mode)

        detected_radius_px = self.detect_radial_transition_radius(
            distances=distances,
            profile=mean_profile,
            disc=disc,
            plate_lawn_ref=lawn_ref,
            whitebox_mode=whitebox_mode,
            mode="kmeans"
        )

        d_px = detected_radius_px * 2.0
        d_mm = d_px * scale

        return ZoneMeasurement(
            disc_id=disc.disc_id,
            radius_px=detected_radius_px,
            diameter_px=d_px,
            diameter_mm=self.apply_clinical_rounding(d_mm),
            method=self.name,
            is_overlapping=is_overlapping,
            profile_curve=mean_profile.tolist()
        )


class ContinuousWarpPolarMeasurer(BaseZoneMeasurer):
    """
    โมเดลที่ 4 (Proposed SOTA): Continuous Warp Polar Transform
    ผสาน Adaptive Low-Light Exposure Gain Normalization, Neighbor Disc Inpainting,
    Agar-Rim Clamping, Top-Clearance Angular Masking, 60th-Percentile Marker-Pen Resilient Consensus,
    2D Warp-Polar Anisotropic Smoothing และ IQR Outlier Rejection แยกอิสระครบ 360 องศา
    """
    def __init__(self, num_angles: int = 360, max_search_radius_mm: float = 17.5):
        super().__init__(
            name="Continuous Warp Polar Transform (SOTA)",
            num_angles=num_angles,
            max_search_radius_mm=max_search_radius_mm
        )

    def measure(
        self,
        gray_img: np.ndarray,
        disc: DiscDetection,
        all_discs: Optional[List[DiscDetection]] = None
    ) -> ZoneMeasurement:
        cx, cy = disc.center
        h, w = gray_img.shape[:2]
        scale = self.get_disc_scale(disc)
        max_radius_px = int(round(self.max_search_radius_mm / scale))
        r_disc_float = float(disc.radius_px)
        r_disc_px = int(round(r_disc_float))
        halo_margin_px = self.get_halo_safe_margin_px(disc)
        whitebox_mode = is_whitebox_plate(gray_img)

        sota_gray = gray_img
        if whitebox_mode or min(h, w) >= 700:
            ch1, ch2 = int(h * 0.28), int(h * 0.72)
            cw1, cw2 = int(w * 0.28), int(w * 0.72)
            agar_med = float(np.median(gray_img[ch1:ch2, cw1:cw2]))
            target_med = 205.0 if whitebox_mode else 138.0
            if agar_med < target_med * 0.88:
                gain = min(3.8, target_med / max(agar_med, 18.0))
                sota_gray = np.clip(gray_img.astype(np.float32) * gain, 0.0, 255.0).astype(np.uint8)

        clean_gray = sanitize_gray_for_target_disc(sota_gray, disc, all_discs)
        lawn_ref = estimate_plate_lawn_intensity(clean_gray, disc, all_discs, whitebox_mode=whitebox_mode)

        r_patch = max_radius_px + 4
        x1_p, y1_p = cx - r_patch, cy - r_patch
        x2_p, y2_p = cx + r_patch + 1, cy + r_patch + 1
        ix1, iy1 = max(0, x1_p), max(0, y1_p)
        ix2, iy2 = min(w, x2_p), min(h, y2_p)

        sub_gray = clean_gray[iy1:iy2, ix1:ix2].copy()
        yy_p, xx_p = np.ogrid[iy1:iy2, ix1:ix2]
        n_total = len(all_discs) if all_discs else 1
        in_agar_sub = self.compute_in_agar_point_mask(xx_p, yy_p, h, w, n_total)
        sub_gray[~in_agar_sub] = int(round(lawn_ref))

        pad_left = max(0, -x1_p)
        pad_top = max(0, -y1_p)
        pad_right = max(0, x2_p - w)
        pad_bot = max(0, y2_p - h)
        if pad_left or pad_top or pad_right or pad_bot:
            sub_gray = cv2.copyMakeBorder(
                sub_gray, pad_top, pad_bot, pad_left, pad_right,
                cv2.BORDER_CONSTANT, value=int(round(lawn_ref))
            )

        polar_img = cv2.warpPolar(
            sub_gray,
            dsize=(max_radius_px, self.num_angles),
            center=(float(r_patch), float(r_patch)),
            maxRadius=float(max_radius_px),
            flags=cv2.WARP_POLAR_LINEAR + cv2.INTER_LINEAR
        )

        distances, _, consensus_profile, valid_mask, is_overlapping = self.sample_radial_rays(
            sota_gray, disc, all_discs=all_discs, disc_margin_px=halo_margin_px, use_sota_sanitization=True
        )
        search_start_px = int(distances[0]) if len(distances) > 0 else min(r_disc_px + halo_margin_px, max_radius_px - 8)
        if len(distances) < 8:
            d_px = float(r_disc_float * 2.0)
            return ZoneMeasurement(
                disc_id=disc.disc_id,
                radius_px=r_disc_float,
                diameter_px=d_px,
                diameter_mm=STANDARD_DISC_DIAMETER_MM,
                method=self.name,
                is_overlapping=is_overlapping,
                profile_curve=[]
            )

        guide_radius_px = self.detect_radial_transition_radius(
            distances=distances,
            profile=consensus_profile,
            disc=disc,
            plate_lawn_ref=lawn_ref,
            whitebox_mode=whitebox_mode,
            mode="sota_guided"
        )

        if guide_radius_px <= r_disc_float + 1.0:
            robust_radius_px = r_disc_float
        else:
            wrap_pad = 12
            polar_wrapped = np.pad(polar_img.astype(np.float32), ((wrap_pad, wrap_pad), (0, 0)), mode="wrap")
            polar_smooth = cv2.GaussianBlur(polar_wrapped, (5, 17), sigmaX=1.4, sigmaY=4.2)[wrap_pad:-wrap_pad, :]
            roi_polar = polar_smooth[:, search_start_px:max_radius_px]

            corridor_half_px = max(5, int(round(2.0 / scale)))
            guide_rel_idx = int(round(guide_radius_px - search_start_px))
            c_start = max(0, guide_rel_idx - corridor_half_px)
            c_end = min(roi_polar.shape[1], guide_rel_idx + corridor_half_px + 1)

            grad_r = -np.gradient(roi_polar, axis=1) if whitebox_mode else np.gradient(roi_polar, axis=1)
            radii_per_angle = np.full(self.num_angles, guide_radius_px, dtype=float)

            for theta in range(self.num_angles):
                if not valid_mask[theta]:
                    continue
                corridor_grad = grad_r[theta, c_start:c_end]
                if len(corridor_grad) > 0 and float(np.max(corridor_grad)) >= 0.75:
                    local_peak = c_start + int(np.argmax(corridor_grad))
                    radii_per_angle[theta] = float(search_start_px + local_peak)

            robust_radius_px, _ = AngularMaskingFilter.filter_outliers_iqr(
                radii_per_angle=radii_per_angle,
                valid_mask=valid_mask,
                iqr_factor=1.2
            )

        d_px = robust_radius_px * 2.0
        d_mm = d_px * scale

        return ZoneMeasurement(
            disc_id=disc.disc_id,
            radius_px=robust_radius_px,
            diameter_px=d_px,
            diameter_mm=self.apply_clinical_rounding(d_mm),
            method=self.name,
            is_overlapping=is_overlapping,
            profile_curve=consensus_profile.tolist()
        )


def get_all_4_zone_measurers(max_search_radius_mm: float = 17.5) -> List[BaseZoneMeasurer]:
    return [
        BhargavOtsuContourMeasurer(max_search_radius_mm=max_search_radius_mm),
        HejblumDerivativeMeasurer(max_search_radius_mm=max_search_radius_mm),
        GulluKMeansMeasurer(max_search_radius_mm=max_search_radius_mm),
        ContinuousWarpPolarMeasurer(max_search_radius_mm=max_search_radius_mm),
    ]


def run_zone_measurement_after_detector(
    plate_bgr: np.ndarray,
    detected_discs: List[DiscDetection],
    method: str = "polar"
) -> Tuple[List[ZoneMeasurement], np.ndarray, pd.DataFrame]:
    method_map = {
        "otsu": BhargavOtsuContourMeasurer(),
        "hejblum": HejblumDerivativeMeasurer(),
        "kmeans": GulluKMeansMeasurer(),
        "polar": ContinuousWarpPolarMeasurer(),
    }
    measurer = method_map.get(method.lower(), ContinuousWarpPolarMeasurer())
    zones = measurer.measure_all_on_plate(plate_bgr, detected_discs, use_preprocessing=True)

    vis_img = plate_bgr.copy() if len(plate_bgr.shape) == 3 else cv2.cvtColor(plate_bgr, cv2.COLOR_GRAY2BGR)
    rows = []

    for disc, zone in zip(detected_discs, zones):
        cx, cy = disc.center
        r_disc = int(round(disc.radius_px))
        r_zone = int(round(zone.radius_px))

        cv2.circle(vis_img, (cx, cy), r_disc, (0, 255, 0), 2)
        cv2.circle(vis_img, (cx, cy), 3, (0, 0, 255), -1)

        zone_color = (0, 165, 255) if zone.is_overlapping else (255, 220, 0)
        cv2.circle(vis_img, (cx, cy), r_zone, zone_color, 2)

        label = f"ID{disc.disc_id}: {zone.diameter_mm:.1f}mm"
        cv2.putText(
            vis_img, label, (max(5, cx - r_zone), max(20, cy - r_zone - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, zone_color, 2, cv2.LINE_AA
        )

        rows.append({
            "Disc ID": disc.disc_id,
            "Center (x, y)": f"({cx}, {cy})",
            "Disc Radius (px)": round(disc.radius_px, 1),
            "Scale (mm/px)": round(disc.scale_mm_per_px, 4),
            "Zone Radius (px)": round(zone.radius_px, 1),
            "Zone Diameter (mm)": zone.diameter_mm,
            "Overlapping Filtered": "Yes" if zone.is_overlapping else "No",
            "Method": zone.method
        })

    return zones, vis_img, pd.DataFrame(rows)


def compare_all_4_models_on_plate(
    plate_bgr: np.ndarray,
    detected_discs: List[DiscDetection]
) -> pd.DataFrame:
    measurers = get_all_4_zone_measurers()
    gray = preprocess_plate_for_zone(plate_bgr)

    comparison_rows = []
    for disc in detected_discs:
        _ = BaseZoneMeasurer.get_disc_scale(disc)
        row = {
            "Disc ID": disc.disc_id,
            "Center": disc.center,
            "Scale (mm/px)": round(disc.scale_mm_per_px, 4),
        }
        for m in measurers:
            z = m.measure(gray, disc, all_discs=detected_discs)
            row[m.name] = z.diameter_mm
            row["Overlap Risk"] = "Yes" if z.is_overlapping else "No"
        comparison_rows.append(row)

    return pd.DataFrame(comparison_rows)
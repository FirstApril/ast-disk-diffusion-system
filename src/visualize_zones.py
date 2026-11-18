"""visualize_zones.py -

โมดูลสร้างภาพแสดงผลการวัดขนาดวงใสและเปรียบเทียบทั้ง 4 อัลกอริทึม
รองรับ:
1. draw_zone_overlay(): วาดขอบแผ่นยา ขอบเขตวงใส เส้นผ่านศูนย์กลาง และป้ายระบุค่า
(mm)
2. create_4way_zone_comparison_grid(): รวมภาพเปรียบเทียบทั้ง 4 วิธีในแบบ 2x2
Grid
3. save_all_evaluation_visualizations(): ฟังก์ชันวนลูปบันทึกภาพทุกเคสอัตโนมัติ
"""

import os
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np


def draw_zone_overlay(
    image: np.ndarray,
    center: Tuple[int, int],
    disc_radius_px: float,
    zone_radius_px: float,
    pred_diameter_mm: float,
    act_diameter_mm: Optional[float] = None,
    method_name: str = "",
    color_bgr: Tuple[int, int, int] = (0, 255, 0),
) -> np.ndarray:
  """วาดวงกลมแผ่นยา ขอบเขตวงใส และกล่องข้อมูลลงบนภาพ"""
  vis = image.copy()
  cx, cy = int(center[0]), int(center[1])
  r_disc = int(round(disc_radius_px))
  r_zone = int(round(zone_radius_px))

  # 1. วาดเส้นขอบวงใส (Outer Zone) และเส้นประแกนเส้นผ่านศูนย์กลาง
  cv2.circle(vis, (cx, cy), r_zone, color_bgr, 2, cv2.LINE_AA)
  cv2.line(
      vis,
      (cx - r_zone, cy),
      (cx + r_zone, cy),
      color_bgr,
      1,
      cv2.LINE_AA,
  )

  # 2. วาดขอบแผ่นยา 6.0 mm (Inner Disc) และจุด Center
  cv2.circle(vis, (cx, cy), r_disc, (255, 200, 0), 2, cv2.LINE_AA)
  cv2.circle(vis, (cx, cy), 3, (0, 0, 255), -1)

  # 3. กล่องข้อความแสดงผลการวัด
  h, w = vis.shape[:2]
  font = cv2.FONT_HERSHEY_SIMPLEX

  text_pred = f"Pred: {pred_diameter_mm:.1f} mm"
  if act_diameter_mm is not None:
    diff = abs(pred_diameter_mm - act_diameter_mm)
    status_color = (0, 255, 0) if diff <= 2.0 else (0, 0, 255)
    text_act = f"Act: {act_diameter_mm:.1f} mm (Err: {diff:.1f})"
  else:
    text_act = ""
    status_color = color_bgr

  # แถบ Header แสดงชื่อโมเดล
  header_title = method_name.split("(")[0].strip()
  cv2.rectangle(vis, (0, 0), (w, 42), (30, 30, 30), -1)
  cv2.putText(
      vis, header_title, (10, 26), font, 0.65, (255, 255, 255), 2, cv2.LINE_AA
  )

  # ป้ายข้อมูลตัวเลขด้านล่าง
  box_h = 55 if act_diameter_mm is not None else 32
  cv2.rectangle(
      vis, (8, h - box_h - 8), (220, h - 8), (20, 20, 20), -1
  )  # พื้นหลังป้าย
  cv2.putText(
      vis,
      text_pred,
      (14, h - box_h + 18),
      font,
      0.55,
      (0, 255, 255),
      1,
      cv2.LINE_AA,
  )
  if text_act:
    cv2.putText(
        vis,
        text_act,
        (14, h - 14),
        font,
        0.50,
        status_color,
        1,
        cv2.LINE_AA,
    )

  return vis


def create_4way_zone_comparison_grid(
    test_sample: Dict[str, Any],
    measurers: List[Any],
    output_size: Tuple[int, int] = (450, 360),
) -> np.ndarray:
  """รันวัดขนาดวงใสทั้ง 4 วิธีกับเม็ดยาเดียวกัน แล้วนำภาพผลลัพธ์มารวมเป็น 2x2 Grid"""
  img = test_sample["image"]
  disc = test_sample["disc"]
  neighbors = test_sample.get("all_discs", [disc])
  act_mm = float(test_sample.get("diameter_act", 0.0))

  cx, cy = disc.center
  r_disc_px = float(disc.radius_px)
  scale = float(disc.scale_mm_per_px)

  # กำหนดสีเฉพาะสำหรับแต่ละโมเดล
  colors = [
      (0, 165, 255),  # 1. Otsu (สีส้ม)
      (0, 255, 0),  # 2. Hejblum (สีเขียว Champion)
      (255, 0, 255),  # 3. K-Means (สีม่วงบานเย็น)
      (0, 255, 255),  # 4. Warp Polar (สีเหลือง)
  ]

  panel_images = []

  for idx, m in enumerate(measurers):
    # วัดขนาดวงใส
    try:
      gray = (
          cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
          if len(img.shape) == 3
          else img.copy()
      )
      res = m.measure(gray, disc, all_discs=neighbors)
      pred_mm = float(res.diameter_mm)
      # คำนวณรัศมีพิกเซลเพื่อนำมาวาดวงกลม
      zone_r_px = max(r_disc_px, (pred_mm / scale) / 2.0)
    except Exception as e:
      pred_mm = 6.0
      zone_r_px = r_disc_px

    # วาดภาพ Overlay
    vis_overlay = draw_zone_overlay(
        image=img,
        center=(cx, cy),
        disc_radius_px=r_disc_px,
        zone_radius_px=zone_r_px,
        pred_diameter_mm=pred_mm,
        act_diameter_mm=act_mm if act_mm > 0 else None,
        method_name=m.name,
        color_bgr=colors[idx % len(colors)],
    )

    resized_panel = cv2.resize(vis_overlay, output_size)
    panel_images.append(resized_panel)

  # จัดเรียงเป็น 2 คอลัมน์ 2 แถว
  top_row = np.hstack([panel_images[0], panel_images[1]])
  bottom_row = np.hstack([panel_images[2], panel_images[3]])
  grid_2x2 = np.vstack([top_row, bottom_row])

  return grid_2x2


def save_comparison_gallery(
    test_records: List[Dict[str, Any]],
    measurers: List[Any],
    output_dir: str = "outputs/zone_comparisons",
    max_cases: int = 8,
):
  """วนลูปบันทึกภาพเปรียบเทียบทั้ง 4 วิธีของหลาย ๆ จานทดสอบ"""
  os.makedirs(output_dir, exist_ok=True)
  print(f"\n-> กำลังสร้างภาพแสดงผลการวัดวงใสบันทึกลงโฟลเดอร์: {output_dir}")

  for i, sample in enumerate(test_records[:max_cases]):
    case_name = sample.get("case_type", f"case_{i+1}")
    grid = create_4way_zone_comparison_grid(sample, measurers)
    filename = f"{output_dir}/comparison_{i+1:02d}_{case_name}.jpg"
    cv2.imwrite(filename, grid)
    print(f"   [บันทึกสำเร็จ] {filename}")

  print(f"-> สร้างภาพ Visualizations ครบ {min(len(test_records), max_cases)} ภาพเรียบร้อยแล้ว!")
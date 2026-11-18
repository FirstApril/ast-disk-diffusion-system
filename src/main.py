import cv2
from detectors import YOLODiscDetector, YOLOv10DiscDetector, HoughCircleDetector
from measurements import (
    run_zone_measurement_after_detector,
    compare_all_4_models_on_plate
)

# 1. โหลดภาพจานเพาะเชื้อ
img = cv2.imread("path/to/img65.jpg")

# 2. จุดที่ 1: รัน Detector เพื่อหาพิกัดเม็ดยา (cx, cy) และรัศมี r_disc
detector = YOLODiscDetector("weights/best_disc_yolo.pt")  # หรือใช้ HoughCircleDetector()
detected_discs = detector.detect(img)
print(f"ตรวจพบเม็ดยาทั้งหมด: {len(detected_discs)} เม็ด")

# 3. จุดที่ 2 (แบบรันใช้งานจริงด้วย SOTA Warp Polar + Angular Masking):
zones, vis_img, df_result = run_zone_measurement_after_detector(
    plate_bgr=img,
    detected_discs=detected_discs,
    method="polar"  # เลือกได้: "polar", "hejblum", "kmeans", "otsu"
)

print("\n--- ผลการวัดขนาดวงใส (Continuous Warp Polar) ---")
print(df_result.to_string(index=False))
cv2.imwrite("output_polar_result.jpg", vis_img)

# 4. จุดที่ 2 (แบบรันเปรียบเทียบทั้ง 4 โมเดลพร้อมกันเพื่อเอาตัวเลขลงเล่ม):
df_compare_4 = compare_all_4_models_on_plate(img, detected_discs)
print("\n--- ตารางเปรียบเทียบทั้ง 4 โมเดลบนจานเดียวกัน ---")
print(df_compare_4.to_string(index=False))
df_compare_4.to_excel("comparison_4_models.xlsx", index=False)
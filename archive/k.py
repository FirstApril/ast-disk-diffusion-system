import cv2  # <-- เพิ่มบรรทัดนี้
from ultralytics import RTDETR

# 1. โหลดโมเดล RT-DETR
model = RTDETR("rtdetr-l.pt")

# 2. รันประเมินภาพ
results = model.predict(
    "dataset/sample_images/img1.png", imgsz=512, conf=0.25, verbose=False
)

# 3. บันทึกผลลัพธ์
res_plotted = results[0].plot()
cv2.imwrite("rtdetr_result.jpg", res_plotted)
print(f"บันทึกภาพผลลัพธ์สำเร็จที่: rtdetr_result.jpg")
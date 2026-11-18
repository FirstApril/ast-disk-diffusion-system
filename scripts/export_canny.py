import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, 'src')):
    if _p not in sys.path: sys.path.insert(0, _p)

"""
export_canny.py - สคริปต์ส่งออกภาพ Canny Edge Map จาก HoughCircleDetector
"""

import argparse
import cv2
from src.detectors import HoughCircleDetector


def main():
  parser = argparse.ArgumentParser(description="Export Canny Edge Map")
  parser.add_argument(
      "--image",
      type=str,
      default="dataset/sample_images/img1.png",
      help="Path รูปภาพ",
  )
  parser.add_argument(
      "--output",
      type=str,
      default="canny_edge_map.jpg",
      help="ชื่อไฟล์ผลลัพธ์",
  )
  args = parser.parse_args()

  img = cv2.imread(args.image)
  detector = HoughCircleDetector()
  edges = detector.get_canny_edge_map(img)

  cv2.imwrite(args.output, edges)
  print(f"[Success] บันทึกภาพ Canny Edge Map สำเร็จที่: {args.output}")


if __name__ == "__main__":
  main()
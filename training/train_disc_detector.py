"""
training/train_disc_detector.py - สคริปต์เทรนโมเดลตรวจจับแผ่นยาปฏิชีวนะ (Kirby-Bauer AST)
รองรับทั้งสถาปัตยกรรม YOLO26 (Anchor-Free) และ YOLOv10 (NMS-Free Real-Time)
รันบนระบบปฏิบัติการ CachyOS และประมวลผลผ่านการ์ดจอ AMD Radeon RX 9070 XT (ROCm 7.2)
"""

import os
import sys
import time
import shutil
import argparse
from pathlib import Path
from typing import Optional, Any, List, Dict
import torch
import pandas as pd
from ultralytics import YOLO


def check_and_prepare_rocm():
    """ตรวจสอบและตั้งค่าสภาพแวดล้อมสำหรับการ์ดจอ AMD Radeon RX 9070 XT บน CachyOS"""
    print("\n" + "=" * 70)
    print(" [1/5] ตรวจสอบสถานะการเชื่อมต่อฮาร์ดแวร์ GPU (AMD ROCm / HIP)")
    print("=" * 70)

    # ลบค่า Override เดิมออก เพื่อให้ RX 9070 XT รันบนสถาปัตยกรรม gfx1201 (RDNA 4) แท้ๆ
    os.environ.pop("HSA_OVERRIDE_GFX_VERSION", None)

    is_rocm = torch.cuda.is_available()
    print(f"-> ROCm GPU Acceleration Active: {is_rocm}")

    if is_rocm:
        device_name = torch.cuda.get_device_name(0)
        vram_bytes = torch.cuda.get_device_properties(0).total_memory
        vram_gb = round(vram_bytes / (1024**3), 2)
        print(f"-> การ์ดจอที่ตรวจพบ           : {device_name}")
        print(f"-> หน่วยความจำ VRAM ทั้งหมด     : {vram_gb} GB (เพียงพอสำหรับ Batch Size 16-32)")
        device_id = 0
    else:
        print("-> [แจ้งเตือน] ไม่พบการ์ดจอ จะทำการรันบน CPU แทน")
        device_id = "cpu"

    print("=" * 70)
    return device_id


def train_disc_detector_pipeline(
    data_yaml: str = "dataset/data.yaml",
    model_variant: str = "yolov10s.pt",
    epochs: int = 300,
    imgsz: int = 512,
    batch_size: int = 16,
    lr0: float = 0.0003,
    patience: int = 50,
    use_clinical_aug: bool = True,
    output_dir: str = "runs_disc",
    weights_dest: Optional[str] = None
):
    """ฟังก์ชันหลักสำหรับสั่งรันเทรนและประเมินผล YOLO26 / YOLOv10"""
    device = check_and_prepare_rocm()

    model_stem = Path(model_variant).stem
    is_v10 = "v10" in model_stem.lower()

    print(f"\n [2/5] โหลดสถาปัตยกรรมโมเดล: {model_variant} (สถาปัตยกรรม: {'YOLOv10 NMS-Free' if is_v10 else 'YOLO26'})")
    model = YOLO(model_variant)

    # --------------------------------------------------------------------------
    # พารามิเตอร์ Data Augmentation & Hyperparameter Tuning
    # --------------------------------------------------------------------------
    if use_clinical_aug:
        print("\n [3/5] เปิดใช้งาน Clinical Data Augmentation + Precision Box Tuning")
        run_name = f"train_{model_stem}"
        aug_config = {
            "hsv_h": 0.01,
            "hsv_s": 0.30,      # ปรับความอิ่มตัวสีพอประมาณ
            "hsv_v": 0.25,      # ปรับความสว่าง
            "degrees": 0.0,     # ปิดการหมุน เพื่อรักษาความคมของขอบสี่เหลี่ยมในชุด Test
            "translate": 0.02,  # ขยับตำแหน่งน้อยมาก
            "scale": 0.10,      # สเกลน้อยมาก
            "fliplr": 0.5,
            "flipud": 0.5,
            "mosaic": 0.0,      # ปิด Mosaic เพื่อไม่ให้สัดส่วน 6 มม. เพี้ยน
            "close_mosaic": 0,
            "mixup": 0.0,
            "box": 8.5,         # เน้นความคมของกรอบ
            "cls": 0.5,
            "dfl": 1.7,
            "lrf": 0.01,
            "cos_lr": True,
            "warmup_epochs": 3.0
        }
    else:
        print("\n [3/5] ปิด Augmentation ทั้งหมด 100% (True Baseline Mode)")
        run_name = f"train_{model_stem}_no_aug"
        aug_config = {
            "hsv_h": 0.0, "hsv_s": 0.0, "hsv_v": 0.0,
            "degrees": 0.0, "translate": 0.0, "scale": 0.0,
            "shear": 0.0, "perspective": 0.0,
            "flipud": 0.0, "fliplr": 0.0,
            "mosaic": 0.0, "close_mosaic": 0, "mixup": 0.0,
            "box": 7.5, "cls": 0.5, "dfl": 1.5,
            "lrf": 0.01, "cos_lr": True, "warmup_epochs": 3.0
        }

    # --------------------------------------------------------------------------
    # เริ่มต้นการเทรนบน GPU RX 9070 XT
    # --------------------------------------------------------------------------
    print(f"\n [4/5] เริ่มต้นกระบวนการเทรนบน GPU ({epochs} Epochs, Batch={batch_size}, ImageSize={imgsz}, LR0={lr0})...\n")
    t_start = time.time()

    train_results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch_size,
        device=device,
        optimizer="AdamW",
        lr0=lr0,
        weight_decay=0.0005,
        patience=patience,
        save=True,
        exist_ok=True,
        project=output_dir,
        name=run_name,
        **aug_config
    )

    train_time_min = round((time.time() - t_start) / 60.0, 2)
    print(f"\n-> การเทรนเสร็จสิ้นเรียบร้อย! ใช้เวลาทั้งหมด: {train_time_min} นาที")

    # --------------------------------------------------------------------------
    # [5/5] ประเมินผลลัพธ์และสกัดตัวชี้วัดสำหรับตารางจุดที่ 1
    # --------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(" [5/5] สรุปผลตัวชี้วัดประสิทธิภาพสำหรับใส่ในเล่มรายงาน (จุดที่ 1)")
    print("=" * 70)

    save_dir = Path(train_results.save_dir)
    best_pt = save_dir / "weights" / "best.pt"
    model_size_mb = round(os.path.getsize(best_pt) / (1024 * 1024), 2) if best_pt.exists() else 0.0

    val_model = YOLO(str(best_pt))
    _ = val_model.val(data=data_yaml, split="test", device=device, verbose=False)
    val_metrics = val_model.val(data=data_yaml, split="test", device=device, verbose=False)

    precision = float(val_metrics.box.mp)
    recall = float(val_metrics.box.mr)
    map50 = float(val_metrics.box.map50)
    map50_95 = float(val_metrics.box.map)
    latency_ms = round(float(val_metrics.speed.get("inference", 3.0)), 2)

    summary_data = [{
        "โมเดล": f"{'YOLOv10' if is_v10 else 'YOLO26'} ({model_stem})",
        "Augmentation": "Clinical (HSV+BoxTune)" if use_clinical_aug else "None",
        "Model Size (MB)": model_size_mb,
        "Inference (ms)": latency_ms,
        "Precision": f"{precision * 100:.2f}%",
        "Recall": f"{recall * 100:.2f}%",
        "mAP50": f"{map50 * 100:.2f}%",
        "mAP50-95": f"{map50_95 * 100:.2f}%"
    }]
    df_summary = pd.DataFrame(summary_data)
    print(df_summary.to_markdown(index=False))

    # กำหนดปลายทางการบันทึกโมเดล
    if weights_dest is None:
        weights_dest = "weights/yolov10s_disc.pt" if is_v10 else "weights/best_disc_yolo.pt"

    if best_pt.exists():
        os.makedirs(os.path.dirname(weights_dest), exist_ok=True)
        shutil.copy(best_pt, weights_dest)
        print(f"\n-> บันทึกโมเดลสำเร็จไปยัง: {weights_dest}")

    csv_out = save_dir / "benchmark_result_point1.csv"
    df_summary.to_csv(csv_out, index=False)
    print(f"-> บันทึกตารางตัวเลขสำหรับเล่มรายงานที่: {csv_out}")
    print("=" * 70)

    return df_summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="สคริปต์เทรน YOLO26 / YOLOv10 สำหรับงานตรวจจับแผ่นยา (Kirby-Bauer AST)")
    parser.add_argument("--data", type=str, default="dataset/data.yaml", help="Path ไปยังไฟล์ data.yaml")
    parser.add_argument("--model", type=str, default="yolov10s.pt", help="สถาปัตยกรรม (yolov10s.pt, yolo26s.pt, yolo26n.pt)")
    parser.add_argument("--epochs", type=int, default=300, help="จำนวนรอบในการเทรน")
    parser.add_argument("--batch", type=int, default=16, help="ขนาด Batch Size")
    parser.add_argument("--imgsz", type=int, default=512, help="ความละเอียดภาพ")
    parser.add_argument("--lr0", type=float, default=0.0003, help="Initial Learning Rate สำหรับ AdamW")
    parser.add_argument("--patience", type=int, default=50, help="จำนวนรอบ Early Stopping")
    parser.add_argument("--no-aug", action="store_true", help="ปิด Clinical Augmentation ทั้งหมด")
    parser.add_argument("--weights-dest", type=str, default=None, help="ปลายทางบันทึก weights")

    args = parser.parse_args()

    train_disc_detector_pipeline(
        data_yaml=args.data,
        model_variant=args.model,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch_size=args.batch,
        lr0=args.lr0,
        patience=args.patience,
        use_clinical_aug=not args.no_aug,
        weights_dest=args.weights_dest
    )
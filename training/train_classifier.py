"""
train_classifier.py - สคริปต์สำหรับแยกเทรนโมเดล ResNet-50 (23 คลาสยา) บนการ์ดจอ RX 9070 XT
ตรงตาม: สถาปัตยกรรมที่ 4 ใน classifiers.py (อ้างอิงเปเปอร์ Gullu et al. 2024 / Pascucci 2021)

คุณสมบัติ:
- ใส่ Data Augmentation หมุน 360 องศา (RandomRotation 180) เพื่อแก้ปัญหาเม็ดยาหมุนเอียง
- ใช้ Transfer Learning จาก ImageNet ResNet-50
- บันทึกผลลัพธ์น้ำหนักโมเดลลงที่: weights/resnet50_disc.pt
"""

import os
import time
from pathlib import Path
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from PIL import Image

# 1. กำหนด Hyperparameters
DATA_DIR = Path("dataset/disc_crops")  # โฟลเดอร์ที่แยกเก็บภาพ Crop เม็ดยาแบ่งตามโฟลเดอร์คลาส
SAVE_PATH = Path("weights/resnet50_disc.pt")
SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 32
EPOCHS = 35
LEARNING_RATE = 0.0005
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# 2. Data Augmentation จัดการปัญหาการหมุนและการเปลี่ยนสภาพแสง
train_transforms = transforms.Compose([
    transforms.Resize((120, 120)),
    transforms.RandomRotation(degrees=180),          # หมุนสุ่ม 360 องศา
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomVerticalFlip(p=0.5),
    transforms.ColorJitter(brightness=0.25, contrast=0.25),  # จำลองแสง 8 สภาวะ
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

def train_resnet():
    print("=" * 75)
    print(f"เริ่มกระบวนการเทรน ResNet-50 บนอุปกรณ์: {DEVICE}")
    print("=" * 75)

    if not DATA_DIR.exists():
        print(f"-> [แจ้งเตือน] ไม่พบโฟลเดอร์ {DATA_DIR}")
        print("-> คำแนะนำ: หากยังไม่มีภาพ Crop แผ่นยา 23 คลาสแยกตามโฟลเดอร์")
        print("   สามารถใช้โมเดล PaddleOCR หรือ EasyOCR ใน classifiers.py รันประเมินผลได้ทันที")
        return

    # โหลด Dataset จากโฟลเดอร์
    from torchvision.datasets import ImageFolder
    train_dataset = ImageFolder(root=str(DATA_DIR), transform=train_transforms)
    num_classes = len(train_dataset.classes)
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=2)

    print(f"-> ตรวจพบชุดข้อมูล: {len(train_dataset)} ภาพ, {num_classes} คลาสยา")

    # 3. สร้างโมเดล ResNet-50
    model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, num_classes)
    model = model.to(DEVICE)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)

    # 4. ลูปการเทรน
    for epoch in range(1, EPOCHS + 1):
        t0 = time.time()
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0

        for inputs, labels in train_loader:
            inputs, labels = inputs.to(DEVICE), labels.to(DEVICE)
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item() * inputs.size(0)
            _, preds = torch.max(outputs, 1)
            correct += torch.sum(preds == labels.data).item()
            total += labels.size(0)

        epoch_loss = running_loss / total
        epoch_acc = (correct / total) * 100.0
        elapsed = time.time() - t0

        print(f"Epoch [{epoch:02d}/{EPOCHS:02d}] - Loss: {epoch_loss:.4f} | Acc: {epoch_acc:.1f}% ({elapsed:.1f}s)")

    # 5. บันทึกโมเดล
    torch.save(model.state_dict(), str(SAVE_PATH))
    print(f"-> บันทึกน้ำหนักโมเดล ResNet-50 สำเร็จที่: {SAVE_PATH}")

if __name__ == "__main__":
    train_resnet()
import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, 'src')):
    if _p not in sys.path: sys.path.insert(0, _p)

"""
Grad-CAM for YOLO11 / YOLO26 Antibiotic Disc Detection
Clinical Explainable AI (XAI) validation for Kirby-Bauer AST
รองรับการแสดงผลความสนใจของแผ่นยาทุกเม็ดบนจานเพาะเชื้อ (Multi-Disc Attention)
"""

import argparse
import os
import sys
import cv2
import numpy as np
import torch
import torch.nn as nn
from ultralytics import YOLO


class YOLOGradCAM:
    def __init__(self, model_path: str, target_layer: str = "auto", device: str = None):
        """
        :param model_path: Path ไปยังไฟล์น้ำหนักโมเดล (.pt)
        :param target_layer: 'auto' (แนะนำ: ดึง P3 Small-object layer อัตโนมัติ) หรือระบุ index (เช่น 16, 15)
        :param device: 'cuda', 'cpu', หรือ ROCm device
        """
        if device is None:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        else:
            self.device = torch.device(device)

        print(f"[Grad-CAM] Loading YOLO model from: {model_path}")
        print(f"[Grad-CAM] Running on device: {self.device}")
        
        yolo = YOLO(model_path)
        self.model = yolo.model.to(self.device)
        self.model.eval()

        # เปิด gradient tracking ให้พารามิเตอร์ของโมเดล
        torch.set_grad_enabled(True)
        for param in self.model.parameters():
            param.requires_grad = True

        self.activations = None
        self.gradients = None
        self.target_layer_str = str(target_layer)
        self._resolve_and_register_hooks()

    def _resolve_and_register_hooks(self):
        """
        ค้นหา Layer ที่เหมาะสมสำหรับตรวจจับแผ่นยาขนาดเล็ก (P3 Stride 8)
        ใน YOLOv8/YOLO11 ชั้น Detect จะรับ input จาก [P3, P4, P5]
        สำหรับแผ่นยา Kirby-Bauer ขนาด 30-35px จะถูกตรวจจับที่ P3 เป็นหลัก
        """
        detect_head = self.model.model[-1]
        
        if self.target_layer_str.lower() == "auto":
            if hasattr(detect_head, 'f') and isinstance(detect_head.f, (list, tuple)):
                # detect_head.f[0] คือ P3 (Small objects / Fine resolution)
                target_idx = detect_head.f[0]
                print(f"[Grad-CAM] Auto-selected P3 (Small-Object Feature Map) layer index: {target_idx}")
            else:
                target_idx = len(self.model.model) - 4
                print(f"[Grad-CAM] Fallback to layer index: {target_idx}")
        else:
            target_idx = int(self.target_layer_str)
            print(f"[Grad-CAM] Using user-specified layer index: {target_idx}")

        target_module = self.model.model[target_idx]
        print(f"[Grad-CAM] Hooked layer [{target_idx}]: {target_module.__class__.__name__}")

        def forward_hook(module, input, output):
            if isinstance(output, (list, tuple)):
                self.activations = output[0]
            else:
                self.activations = output
            
            if self.activations.requires_grad:
                self.activations.retain_grad()
            
            def tensor_backward_hook(grad):
                self.gradients = grad
            
            self.activations.register_hook(tensor_backward_hook)

        target_module.register_forward_hook(forward_hook)

    def preprocess(self, img_bgr: np.ndarray, imgsz: int = 640) -> torch.Tensor:
        """แปลงภาพเป็น Tensor ขนาด 640 พร้อมเปิด requires_grad"""
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img_resized = cv2.resize(img_rgb, (imgsz, imgsz))
        tensor = torch.from_numpy(img_resized).float() / 255.0
        tensor = tensor.permute(2, 0, 1).unsqueeze(0).to(self.device)
        tensor.requires_grad_(True)
        return tensor

    def generate(self, img_bgr: np.ndarray, imgsz: int = 640, conf_thresh: float = 0.20) -> np.ndarray:
        orig_h, orig_w = img_bgr.shape[:2]
        input_tensor = self.preprocess(img_bgr, imgsz=imgsz)

        self.model.zero_grad()
        if input_tensor.grad is not None:
            input_tensor.grad.zero_()

        with torch.enable_grad():
            preds = self.model(input_tensor)
            
            if isinstance(preds, (list, tuple)):
                pred_tensor = preds[0]
            else:
                pred_tensor = preds

            # ดึงค่า Confidence ของแผ่นยา (Shape: [1, 4 + nc, num_anchors])
            if pred_tensor.dim() >= 3 and pred_tensor.shape[1] > 4:
                class_scores = pred_tensor[:, 4:, :]
            else:
                class_scores = pred_tensor

            # คำนวณ Score จากแผ่นยาทุกเม็ดที่โมเดลตรวจพบ (Multi-disc scoring)
            high_conf_mask = class_scores > conf_thresh
            if high_conf_mask.sum() > 0:
                score = class_scores[high_conf_mask].sum()
                num_detected = high_conf_mask.sum().item()
                print(f"[Grad-CAM] Detected {num_detected} anchor activations above conf {conf_thresh}")
            else:
                # กรณีโมเดลยังมีค่า confidence ไม่สูง ให้ดึง Top-30 anchors ที่เด่นที่สุด
                k = min(30, class_scores.numel())
                topk_scores, _ = torch.topk(class_scores.reshape(-1), k=k)
                score = topk_scores.sum()
                print(f"[Grad-CAM] Fallback: using sum of top-{k} detection scores")

            if not score.requires_grad or score.grad_fn is None:
                raise RuntimeError("Score tensor lacks grad_fn. Ensure model gradients are unfrozen.")

            score.backward()

        if self.activations is None or self.gradients is None:
            raise RuntimeError("[Grad-CAM] Failed to capture activations/gradients.")

        # คำนวณ GAP Weights จาก Gradients
        gradients = self.gradients.detach()
        activations = self.activations.detach()

        weights = torch.mean(gradients, dim=(2, 3), keepdim=True)
        cam = torch.sum(weights * activations, dim=1, keepdim=True)
        cam = torch.relu(cam)

        cam = cam.squeeze().cpu().numpy()
        cam = cv2.resize(cam, (orig_w, orig_h))
        
        # ปรับ Normalize ให้อยู่ในช่วง 0.0 - 1.0
        cam_min, cam_max = cam.min(), cam.max()
        if cam_max > cam_min:
            cam = (cam - cam_min) / (cam_max - cam_min)
        else:
            print("[Warning] CAM has zero dynamic range. Ensure correct weights and image path.")
            cam = np.zeros_like(cam)

        # สร้าง Heatmap สี JET (สีแดง = ความสำคัญสูงสุด, น้ำเงิน = พื้นหลัง)
        heatmap = cv2.applyColorMap(np.uint8(255 * cam), cv2.COLORMAP_JET)

        # ผสมภาพ Heatmap เข้ากับภาพเดิม
        overlay = cv2.addWeighted(img_bgr, 0.6, heatmap, 0.4, 0)
        return overlay, cam


def find_default_model() -> str:
    """ค้นหาไฟล์น้ำหนักที่เทรนไว้แล้วในโปรเจกต์อัตโนมัติ"""
    candidates = [
        "weights/best_disc_yolo.pt",
        "runs_disc/weights/best.pt",
        "runs/detect/disc_yolo/weights/best.pt",
        "runs/detect/train/weights/best.pt",
        "best.pt",
        "yolo11n.pt"
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "yolo11n.pt"


def main():
    parser = argparse.ArgumentParser(description="YOLO Grad-CAM for Antibiotic Disc Detection (Multi-Disc XAI)")
    parser.add_argument("--model", type=str, default=None, help="Path to weights (.pt). Default: auto-search best.pt")
    parser.add_argument("--image", type=str, required=True, help="Path to input petri dish image")
    parser.add_argument("--output", type=str, default="gradcam_result.jpg", help="Path to save output heatmap")
    parser.add_argument("--target-layer", type=str, default="auto", help="Layer index or 'auto' (P3 small disc layer)")
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    parser.add_argument("--conf", type=float, default=0.20, help="Confidence threshold for disc attention")
    args = parser.parse_args()

    # เลือกไฟล์ Model
    model_path = args.model if args.model else find_default_model()
    if not os.path.exists(model_path):
        print(f"[Warning] Model file not found at {model_path}. Falling back to yolo11n.pt...", file=sys.stderr)
        model_path = "yolo11n.pt"

    # ตรวจสอบรูปภาพ
    if not os.path.exists(args.image):
        print(f"[Error] Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(args.image)
    if img is None:
        print(f"[Error] Unable to read image file: {args.image}", file=sys.stderr)
        sys.exit(1)

    # รัน Grad-CAM
    cam_generator = YOLOGradCAM(model_path=model_path, target_layer=args.target_layer)
    result_overlay, cam_raw = cam_generator.generate(img, imgsz=args.imgsz, conf_thresh=args.conf)

    # บันทึกผลลัพธ์
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or '.', exist_ok=True)
    cv2.imwrite(args.output, result_overlay)
    print(f"[Success] Grad-CAM visualization saved to: {args.output}")
    print(f"[Info] CAM Range: min={cam_raw.min():.4f}, max={cam_raw.max():.4f}")


if __name__ == "__main__":
    main()
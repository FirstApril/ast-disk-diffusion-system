#!/usr/bin/env python3
"""
organize_project.py - สคริปต์จัดระเบียบโครงสร้างโปรเจกต์ ATSProject อัตโนมัติ (อัปเดตให้ตรงกับหน้าจอ VS Code ล่าสุด)
หน้าที่:
1. ย้ายไฟล์ที่กระจัดกระจายอยู่หน้าแรก (Root) เข้าโฟลเดอร์หมวดหมู่ที่ถูกต้องครบทุกไฟล์:
   - โมดูลหลัก (`visualize_zones.py`, `measurements.py`, `classifiers.py`, `ast_database.py`, `drug_reader.py`) -> `src/`
   - สคริปต์ทดสอบเปรียบเทียบ (`compare_point1.py`, `compare_point2*.py`, `compare_point3.py`) -> `benchmarks/`
   - สคริปต์สกัดภาพและเครื่องมือ (`export_process_stages.py`, `export_canny.py`, `gradcam_yolo.py`, `extract_disc_dataset.py`) -> `scripts/`
   - สคริปต์เทรนโมเดล (`train_classifier.py`) -> `training/`
   - ไฟล์น้ำหนักโมเดลทั้งหมดในหน้าแรก (`yolo11n.pt`, `yolo26n.pt`, `yolo26s.pt`, `yolov8s-worldv2.pt`, `yolov10s.pt`, `rtdetr-l.pt`) -> `weights/`
   - ไฟล์ตารางผลการทดลองทั้งหมด (`point1_comparison_no-tune.*`, `point2_real_*_detailed.csv`, `point2_real_comparison.csv`, `point3_comparison.*`, `point3_position_linked_table*`) -> `outputs/tables/`
   - ไฟล์รูปภาพผลลัพธ์ในหน้าแรก (`rtdetr_result.jpg`, `yolo_world_result.jpg`, `canny_edge_map.jpg`, `gradcam_test1.jpg`) -> `outputs/figures/`
   - ไฟล์แอป Flutter (`main.dart`, `pubspec.yaml`) -> จัดเข้าโครงสร้าง `ast_flutter_app/lib/main.dart` และ `ast_flutter_app/pubspec.yaml` พร้อมสำเนา `ast_api_payload.json` เข้า `ast_flutter_app/assets/data/`
2. ปรับ `sys.path` และ Path ของโมเดลในสคริปต์อัตโนมัติ เพื่อให้รันคำสั่งจากหน้าแรกได้ทันทีโดยไม่เกิด `ModuleNotFoundError` หรือ `FileNotFoundError`

วิธีรัน:
  python organize_project.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 1. แผนผังการย้ายไฟล์ระบุชื่อชัดเจน
MOVE_MAP = {
    "src": [
        "visualize_zones.py",
        "measurements.py",
        "classifiers.py",
        "ast_database.py",
        "drug_reader.py",
        "schemas.py",
    ],
    "benchmarks": [
        "compare_point1.py",
        "compare_point2.py",
        "compare_point2_real.py",
        "compare_point3.py",
    ],
    "scripts": [
        "export_process_stages.py",
        "export_canny.py",
        "gradcam_yolo.py",
        "src/extract_disc_dataset.py",
        "extract_disc_dataset.py",
    ],
    "training": [
        "train_classifier.py",
    ],
    "weights": [
        "rtdetr-l.pt",
        "yolo11n.pt",
        "yolo26n.pt",
        "yolo26s.pt",
        "yolov8s-worldv2.pt",
        "yolov10s.pt",
    ],
    "outputs/tables": [
        "point1_comparison.csv",
        "point1_comparison.md",
        "point1_comparison_no_tune.csv",
        "point1_comparison_no_tune.md",
        "point1_comparison_no-tune.csv",
        "point1_comparison_no-tune.md",
        "point2_comparison.csv",
        "point2_comparison.md",
        "point2_real_comparison.csv",
        "point2_real_1_120_detailed.csv",
        "point2_real_65_120_detailed.csv",
        "point3_comparison.csv",
        "point3_comparison.md",
    ],
    "outputs/figures": [
        "canny_edge_map.jpg",
        "gradcam_test1.jpg",
        "rtdetr_result.jpg",
        "yolo_world_result.jpg",
    ],
    "docs": [
        "Project Structure Agreement.txt",
        "antibiotic_app_architecture_workflow.md",
        "เปรียบเทียบโมเดล.md",
        "system_requirements.txt",
    ],
    "archive": [
        "k.py",
        "requirementsOri.txt",
    ],
    "ast_flutter_app/lib": [
        "main.dart",
    ],
    "ast_flutter_app": [
        "pubspec.yaml",
    ],
}

# 2. รูปแบบไฟล์เพิ่มเติมในหน้าแรก (Root) ที่ให้กวาดเข้าหมวดหมู่อัตโนมัติ
ROOT_GLOB_RULES = [
    ("point*.csv", "outputs/tables"),
    ("point*.md", "outputs/tables"),
    ("*.pt", "weights"),
    ("*_result.jpg", "outputs/figures"),
    ("*_result.png", "outputs/figures"),
]

SYS_PATH_HEADER = (
    "import sys, os\n"
    "_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
    "for _p in (_ROOT, os.path.join(_ROOT, 'src')):\n"
    "    if _p not in sys.path:\n"
    "        sys.path.insert(0, _p)\n\n"
)


def ensure_sys_path_in_script(py_file: Path) -> None:
    """เพิ่ม sys.path อัตโนมัติในไฟล์ .py ที่ถูกย้ายเข้าโฟลเดอร์ย่อย เพื่อให้ import โมดูลจาก src/ ได้เสมอ"""
    try:
        content = py_file.read_text(encoding="utf-8")
        if "_ROOT = os.path.dirname" in content or "PROJECT_ROOT =" in content:
            return
        py_file.write_text(SYS_PATH_HEADER + content, encoding="utf-8")
    except Exception:
        pass


def move_single_file(src_file: Path, target_subdir: str) -> bool:
    if not src_file.exists() or not src_file.is_file():
        return False

    dest_dir = ROOT / target_subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / src_file.name

    if src_file.resolve() == dest_file.resolve():
        return False

    rel_src = src_file.relative_to(ROOT)
    shutil.move(str(src_file), str(dest_file))

    if dest_file.suffix == ".py" and target_subdir in ("benchmarks", "scripts", "training"):
        ensure_sys_path_in_script(dest_file)

    print(f"  [ย้ายสำเร็จ] {str(rel_src):<38} -> {target_subdir}/{src_file.name}")
    return True


def setup_flutter_folders() -> None:
    """เตรียมโฟลเดอร์ assets สำหรับโปรเจกต์ Flutter และสำเนาไฟล์ JSON ฐานข้อมูลหากมีอยู่แล้ว"""
    flutter_dir = ROOT / "ast_flutter_app"
    models_dir = flutter_dir / "assets" / "models"
    data_dir = flutter_dir / "assets" / "data"
    models_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    json_payload = ROOT / "database" / "ast_api_payload.json"
    if json_payload.exists():
        dest_json = data_dir / "ast_api_payload.json"
        shutil.copy2(str(json_payload), str(dest_json))
        print(f"  [ซิงค์ข้อมูล] database/ast_api_payload.json          -> ast_flutter_app/assets/data/ast_api_payload.json")


def print_clean_root_summary() -> None:
    print("\nรายการโฟลเดอร์และไฟล์หลักที่หน้าแรก (Root) หลังจัดระเบียบ:")
    items = sorted(ROOT.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    for item in items:
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
        prefix = "[DIR] " if item.is_dir() else "[FILE]"
        print(f"  {prefix} {item.name}")


def organize_workspace() -> None:
    print("=" * 88)
    print(f"เริ่มจัดระเบียบโครงสร้างโปรเจกต์ที่: {ROOT}")
    print("=" * 88)

    moved_count = 0

    # ขั้นที่ 1: ย้ายตามรายชื่อไฟล์ใน MOVE_MAP
    for target_subdir, file_list in MOVE_MAP.items():
        for rel_path in file_list:
            src_file = ROOT / rel_path
            if move_single_file(src_file, target_subdir):
                moved_count += 1

    # ขั้นที่ 2: กวาดไฟล์ที่ตรงตามรูปแบบ (เช่น point*.csv, *.pt) ที่ยังตกค้างอยู่ในหน้าแรก
    for pattern, target_subdir in ROOT_GLOB_RULES:
        for matched_file in sorted(ROOT.glob(pattern)):
            if matched_file.name == Path(__file__).name:
                continue
            if move_single_file(matched_file, target_subdir):
                moved_count += 1

    # ขั้นที่ 3: เตรียมโครงสร้างโฟลเดอร์สำหรับแอป Flutter
    setup_flutter_folders()

    print("=" * 88)
    print(f"จัดระเบียบเสร็จสมบูรณ์! ย้ายไฟล์เข้าหมวดหมู่ทั้งหมด {moved_count} ไฟล์")
    print("=" * 88)

    print_clean_root_summary()

    print("\nคำสั่งรันงานหลังจัดระเบียบ:")
    print("  1. รันประเมินการวัดวงใส (Point 2): python benchmarks/compare_point2_real.py --start 1 --end 120")
    print("  2. รันตารางเชื่อมตามพิกัด (Point 3): python benchmarks/compare_point3.py --start 65 --end 120")
    print("  3. อัปเดตฐานข้อมูลกลาง (Point 4):  python src/ast_database.py --init-db")
    print("  4. สกัดภาพ 6 ขั้นตอนใส่เล่มวิจัย:    python scripts/export_process_stages.py --image dataset/sample_images/img85.png --disc 0")


if __name__ == "__main__":
    organize_workspace()
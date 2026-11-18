"""
Antibiogram Analysis Data Schemas (Step 1: Data Contract & Domain Models)
Defines Pydantic models for:
1. Spatial geometry (BoundingBox, Point)
2. Disc detection & calibration (DiscDetection)
3. Zone of inhibition measurement (ZoneMeasurement)
4. Clinical interpretation according to CLSI M100 / EUCAST (AntibiogramItemResult)
5. Comprehensive plate report (PlateAnalysisReport)
"""

from enum import Enum
from typing import List, Tuple, Optional, Dict, Any
from pydantic import BaseModel, Field, computed_field
from datetime import datetime
import pandas as pd

# Physical standard for antibiotic disc (CLSI / EUCAST)
STANDARD_DISC_DIAMETER_MM: float = 6.0


class SIRStatus(str, Enum):
    """Clinical antimicrobial susceptibility interpretation categories."""
    SUSCEPTIBLE = "S"          # ไวต่อยา (Sensitive / Susceptible)
    INTERMEDIATE = "I"         # ปานกลาง / ไวต่อยาตามขนาดยา (Intermediate / SDD)
    RESISTANT = "R"            # ดื้อยา (Resistant)
    UNKNOWN = "N/A"            # ไม่สามารถแปลผลได้ / ไม่มีเกณฑ์


class BoundingBox(BaseModel):
    """2D Bounding Box in image pixel coordinates [x1, y1, x2, y2]."""
    x1: int = Field(ge=0, description="Top-left X coordinate")
    y1: int = Field(ge=0, description="Top-left Y coordinate")
    x2: int = Field(ge=0, description="Bottom-right X coordinate")
    y2: int = Field(ge=0, description="Bottom-right Y coordinate")

    @computed_field
    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @computed_field
    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @computed_field
    @property
    def center(self) -> Tuple[int, int]:
        return (int((self.x1 + self.x2) / 2), int((self.y1 + self.y2) / 2))


class DiscDetection(BaseModel):
    """Data model representing a detected antibiotic disc."""
    disc_id: int = Field(description="Sequential ID of the disc on the plate (e.g. 1..N)")
    center: Tuple[int, int] = Field(description="Center coordinate (cx, cy) in pixels")
    radius_px: float = Field(gt=0, description="Detected disc radius in pixels")
    diameter_px: float = Field(gt=0, description="Detected disc diameter in pixels (2 * radius)")
    bbox: BoundingBox = Field(description="Bounding box surrounding the disc")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Detection confidence score")
    detector_type: str = Field(default="YOLO", description="Detector algorithm used (e.g. YOLOv8, HoughCircle)")
    
    # Antibiotic code & identification
    code: Optional[str] = Field(default=None, description="Antibiotic short code (e.g. AMP10, CIP5, FOX30)")
    code_confidence: Optional[float] = Field(default=None, description="OCR / Classifier confidence for disc code")

    @computed_field
    @property
    def scale_mm_per_px(self) -> float:
        """
        Conversion scale factor from pixel to millimeter based on
        the standard physical disc diameter of 6.0 mm.
        Formula: Scale = 6.0 mm / diameter_px
        """
        return STANDARD_DISC_DIAMETER_MM / self.diameter_px


class ZoneMeasurement(BaseModel):
    """Data model representing an inhibition zone measurement."""
    disc_id: int = Field(description="Reference ID of the centered antibiotic disc")
    radius_px: float = Field(ge=0, description="Measured clear zone radius from center to boundary in pixels")
    diameter_px: float = Field(ge=0, description="Clear zone diameter in pixels (2 * radius_px)")
    diameter_mm: float = Field(ge=0, description="Clear zone diameter converted to physical millimeters (mm)")
    method: str = Field(default="RadialProfile_KMeans", description="Algorithm used to detect zone boundary")
    is_overlapping: bool = Field(default=False, description="Flag indicating if the zone overlaps with adjacent zones")
    profile_curve: Optional[List[float]] = Field(default=None, description="1D radial intensity profile curve values")


class AntibiogramItemResult(BaseModel):
    """Final clinical result for a single antibiotic disc on the plate."""
    disc_id: int
    code: str = Field(description="Antibiotic short code (e.g. 'AMP10')")
    antibiotic_name: Optional[str] = Field(default=None, description="Full drug name (e.g. 'Ampicillin 10 mcg')")
    diameter_mm: float = Field(description="Measured inhibition zone diameter in mm")
    sir: SIRStatus = Field(description="Clinical susceptibility interpretation (S / I / R)")
    guideline: str = Field(default="CLSI M100", description="Evaluation standard (CLSI M100 or EUCAST)")
    breakpoint_applied: Optional[Dict[str, Any]] = Field(default=None, description="Breakpoints used for evaluation")


class PlateAnalysisReport(BaseModel):
    """Complete summary report of an analyzed petri dish image."""
    image_name: str = Field(description="Filename or path of the analyzed image")
    bacteria_species: Optional[str] = Field(default=None, description="Tested bacterial organism (e.g. E. coli)")
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp of analysis")
    total_discs_detected: int = Field(ge=0, description="Total count of antibiotic discs detected")
    plate_mean_scale_mm_per_px: float = Field(description="Average plate calibration scale (mm/px)")
    results: List[AntibiogramItemResult] = Field(default_factory=list, description="List of per-antibiotic results")

    def to_dataframe(self) -> pd.DataFrame:
        """Converts results into a pandas DataFrame for reporting / saving to Excel."""
        records = []
        for item in self.results:
            records.append({
                "Disc ID": item.disc_id,
                "Antibiotic Code": item.code,
                "Antibiotic Name": item.antibiotic_name or item.code,
                "Zone Diameter (mm)": round(item.diameter_mm, 2),
                "Interpretation (SIR)": item.sir.value,
                "Guideline": item.guideline
            })
        return pd.DataFrame(records)

    def summary_markdown(self) -> str:
        """Generates a clean Markdown summary table."""
        df = self.to_dataframe()
        return df.to_markdown(index=False)

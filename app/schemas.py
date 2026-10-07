from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MeasurementStatus = Literal["OK", "NOT_APPLICABLE", "UNSUPPORTED", "INVALID"]


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: Literal["PROCESSING", "COMPLETED", "FAILED"]
    error: str | None = None
    geometry_types: dict[str, int] = Field(default_factory=dict)
    created_at: datetime


class Measurement(BaseModel):
    status: MeasurementStatus
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    # Polygon / MultiPolygon
    area_sq_m: float | None = None
    area_hectares: float | None = None
    perimeter_m: float | None = None
    # LineString / MultiLineString
    length_m: float | None = None
    length_km: float | None = None
    # How the numbers were obtained
    projected_crs: str | None = None
    projection_strategy: str | None = None
    geodesic_check: dict[str, float] | None = None


class MeasurementItem(BaseModel):
    index: int
    geometry_type: str
    crs: str | None
    measurement: Measurement


class MeasurementSummary(BaseModel):
    total_area_sq_m: float
    total_length_m: float
    by_status: dict[str, int]


class MeasurementList(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    summary: MeasurementSummary
    items: list[MeasurementItem]


class FeatureOut(BaseModel):
    index: int
    geometry_type: str
    geometry: dict[str, Any] | None
    crs: str | None
    properties: dict[str, Any]


class FeatureList(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    items: list[FeatureOut]

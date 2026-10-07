from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

PROCESSING, COMPLETED, FAILED = "PROCESSING", "COMPLETED", "FAILED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UploadedFile(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))  # "kml" | "shapefile"
    status: Mapped[str] = mapped_column(String(16), default=PROCESSING)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry_types: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    features: Mapped[list["Feature"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="Feature.index"
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    geometry_type: Mapped[str] = mapped_column(String(32))
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # GeoJSON, source CRS
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    measurement: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    file: Mapped[UploadedFile] = relationship(back_populates="features")

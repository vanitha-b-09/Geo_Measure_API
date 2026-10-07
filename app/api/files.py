import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import FAILED, Feature, UploadedFile
from app.schemas import (
    FeatureList,
    FeatureOut,
    FileInfo,
    MeasurementItem,
    MeasurementList,
    MeasurementSummary,
)
from app.services.processor import process_upload
from app.services.readers import detect_kind

router = APIRouter(prefix="/api/files", tags=["files"])
CHUNK = 1024 * 1024


def _get_file(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(404, "File not found")
    return record


@router.post(
    "/",
    response_model=FileInfo,
    status_code=201,
    summary="Upload a .kml or a .zip (Shapefile) and process it",
    responses={
        413: {"description": "File too large"},
        415: {"description": "Unsupported file type"},
        422: {"description": "File could not be parsed as geospatial data"},
    },
)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = Path(file.filename or "").name
    if not filename or detect_kind(filename) is None:
        raise HTTPException(415, "Unsupported file type. Upload a .kml file or a .zip containing a Shapefile.")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload"
        size = 0
        with path.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, f"File exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "Uploaded file is empty")
        record = process_upload(db, filename, path)

    if record.status == FAILED:
        return JSONResponse(
            status_code=422,
            content={"detail": record.error, "file": FileInfo.model_validate(record).model_dump(mode="json")},
        )
    return record


@router.get("/{file_id}/", response_model=FileInfo, summary="File information")
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_file(db, file_id)


@router.get("/{file_id}/features/", response_model=FeatureList, summary="Extracted features (geometry + attributes)")
def list_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _get_file(db, file_id)
    total = db.scalar(select(func.count()).select_from(Feature).where(Feature.file_id == file_id))
    rows = db.scalars(
        select(Feature).where(Feature.file_id == file_id).order_by(Feature.index).offset(offset).limit(limit)
    ).all()
    return FeatureList(
        file_id=file_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[
            FeatureOut(
                index=r.index, geometry_type=r.geometry_type, geometry=r.geometry, crs=r.crs, properties=r.properties
            )
            for r in rows
        ],
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementList, summary="Per-feature measurements")
def list_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _get_file(db, file_id)
    rows = db.scalars(
        select(Feature).where(Feature.file_id == file_id).order_by(Feature.index).offset(offset).limit(limit)
    ).all()

    # Summary spans the whole file (not just the requested page).
    total_area = total_length = 0.0
    by_status: dict[str, int] = {}
    all_measurements = db.scalars(select(Feature.measurement).where(Feature.file_id == file_id)).all()
    for m in all_measurements:
        by_status[m["status"]] = by_status.get(m["status"], 0) + 1
        total_area += m.get("area_sq_m") or 0.0
        total_length += m.get("length_m") or 0.0

    return MeasurementList(
        file_id=file_id,
        total=len(all_measurements),
        limit=limit,
        offset=offset,
        summary=MeasurementSummary(
            total_area_sq_m=round(total_area, 3), total_length_m=round(total_length, 3), by_status=by_status
        ),
        items=[
            MeasurementItem(index=r.index, geometry_type=r.geometry_type, crs=r.crs, measurement=r.measurement)
            for r in rows
        ],
    )

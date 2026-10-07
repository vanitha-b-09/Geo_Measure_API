"""Orchestrates: read file -> extract features -> measure -> persist."""
import logging
import tempfile
import uuid
from collections import Counter
from pathlib import Path

from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app.errors import InvalidFileError
from app.models import COMPLETED, FAILED, Feature, UploadedFile
from app.services.measurements import Measurer
from app.services.readers import crs_label, detect_kind, read_dataset

log = logging.getLogger(__name__)


def process_upload(db: Session, filename: str, path: Path) -> UploadedFile:
    kind = detect_kind(filename)
    record = UploadedFile(id=uuid.uuid4().hex, filename=filename, file_type=kind)
    db.add(record)
    db.commit()

    try:
        with tempfile.TemporaryDirectory() as workdir:
            dataset = read_dataset(kind, path, Path(workdir))

        crs = crs_label(dataset.crs)
        measurer = Measurer(dataset.crs)
        type_counts: Counter[str] = Counter()
        rows = []
        for f in dataset.features:
            geom_type = f.geometry.geom_type if f.geometry is not None else (f.geometry_type or "None")
            type_counts[geom_type] += 1
            if f.error:
                measurement = {"status": f.error_status, "message": f.error, "warnings": []}
            else:
                measurement = measurer.measure(f.geometry)
            rows.append(
                Feature(
                    file_id=record.id,
                    index=f.index,
                    geometry_type=geom_type,
                    geometry=mapping(f.geometry) if f.geometry is not None else None,
                    crs=crs,
                    properties=f.properties,
                    measurement=measurement,
                )
            )
        db.add_all(rows)
        record.crs = crs
        record.feature_count = len(rows)
        record.geometry_types = dict(type_counts)
        record.status = COMPLETED
        db.commit()
    except InvalidFileError as exc:
        db.rollback()
        record.status, record.error = FAILED, str(exc)
        db.commit()
    except Exception:  # unexpected: log details, return a generic message
        log.exception("Unexpected error processing %s", filename)
        db.rollback()
        record.status, record.error = FAILED, "Unexpected error while processing the file"
        db.commit()
    return record

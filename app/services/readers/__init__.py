from pathlib import Path

from app.config import settings
from app.errors import InvalidFileError
from app.services.readers.base import ParsedDataset, crs_label
from app.services.readers.kml import read_kml
from app.services.readers.shapefile import read_shapefile_zip

__all__ = ["read_dataset", "crs_label", "ParsedDataset", "detect_kind"]


def detect_kind(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower()
    return {".kml": "kml", ".zip": "shapefile"}.get(suffix)


def read_dataset(kind: str, path: Path, workdir: Path) -> ParsedDataset:
    if kind == "kml":
        return read_kml(path.read_bytes(), settings.max_features)
    if kind == "shapefile":
        return read_shapefile_zip(path, workdir, settings.max_features)
    raise InvalidFileError(f"Unsupported file type: {kind}")

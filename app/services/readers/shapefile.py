"""Shapefile (.zip) reader built on GeoPandas/pyogrio.

The archive is extracted defensively (zip-slip, zip-bomb and junk-file checks)
into a temp directory, then read with GDAL. The CRS comes from the .prj file.
"""
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import geopandas as gpd

from app.config import settings
from app.errors import InvalidFileError
from app.services.readers.base import ParsedDataset, ParsedFeature, json_safe

# Let GDAL rebuild a missing .shx index instead of failing.
os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")

ALLOWED_SUFFIXES = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


def _safe_extract(zip_path: Path, dest: Path) -> None:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise InvalidFileError("File is not a valid zip archive") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > settings.max_zip_members:
            raise InvalidFileError("Zip archive contains too many files")
        if sum(i.file_size for i in infos) > settings.max_unzipped_bytes:
            raise InvalidFileError("Zip archive is too large when uncompressed")
        for info in infos:
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if "__MACOSX" in parts or parts[-1].startswith("._"):
                continue
            if PurePosixPath(parts[-1]).suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            target = dest.joinpath(*parts).resolve()
            if not target.is_relative_to(dest.resolve()):  # zip-slip
                raise InvalidFileError("Zip archive contains an unsafe path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def read_shapefile_zip(zip_path: Path, workdir: Path, max_features: int) -> ParsedDataset:
    dest = workdir / "shp"
    dest.mkdir()
    _safe_extract(zip_path, dest)

    shp_files = sorted(p for p in dest.rglob("*") if p.is_file() and p.suffix.lower() == ".shp")
    if not shp_files:
        raise InvalidFileError("Zip archive does not contain a .shp file")
    if len(shp_files) > 1:
        raise InvalidFileError("Zip archive contains multiple shapefiles; upload one per archive")

    try:
        gdf = gpd.read_file(shp_files[0], engine="pyogrio")
    except Exception as exc:  # GDAL raises a variety of errors on corrupt data
        raise InvalidFileError(f"Could not read shapefile: {exc}") from exc

    if gdf.crs is None:
        raise InvalidFileError("Shapefile has no CRS (.prj file missing or unreadable)")
    if len(gdf) > max_features:
        raise InvalidFileError(f"File has more than {max_features} features")

    geom_col = gdf.geometry.name
    records = gdf.drop(columns=[geom_col]).to_dict("records")
    features = [
        ParsedFeature(
            index=i,
            geometry=geom,
            properties={str(k): json_safe(v) for k, v in props.items()},
            geometry_type=None if geom is not None else "None",
            error=None if geom is not None else "Feature has no geometry",
            error_status="UNSUPPORTED",
        )
        for i, (geom, props) in enumerate(zip(gdf.geometry, records))
    ]
    return ParsedDataset(crs=gdf.crs, features=features)

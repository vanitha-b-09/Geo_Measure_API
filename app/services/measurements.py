"""Area / length calculation.

Flow for each geometry:
  source CRS -> WGS84 (to pick a projection) -> local projected CRS -> measure.
A geodesic (ellipsoidal) value is computed too as an independent sanity check.
Nothing is ever measured in degrees.
"""
import math
from typing import Any

import shapely
from pyproj import Geod, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from app.services.projection import select_projection

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "LinearRing", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}

_GEOD = Geod(ellps="WGS84")


def _result(status: str, message: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"status": status, "message": message, "warnings": [], **extra}


def _geodesic_area(geom: BaseGeometry) -> float:
    total = 0.0
    for poly in getattr(geom, "geoms", [geom]):
        area = abs(_GEOD.polygon_area_perimeter(*poly.exterior.xy)[0])
        for ring in poly.interiors:
            area -= abs(_GEOD.polygon_area_perimeter(*ring.xy)[0])
        total += area
    return total


def _geodesic_length(geom: BaseGeometry) -> float:
    return sum(_GEOD.line_length(*line.xy) for line in getattr(geom, "geoms", [geom]))


class Measurer:
    """Bound to one source CRS; caches the (non-thread-safe) pyproj transformers."""

    def __init__(self, source_crs):
        self._source_crs = source_crs
        self._to_wgs84 = (
            None
            if source_crs.to_epsg() == 4326
            else Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
        )
        self._cache: dict[str, Transformer] = {}

    def _projector(self, crs: str) -> Transformer:
        if crs not in self._cache:
            self._cache[crs] = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        return self._cache[crs]

    def measure(self, geom: BaseGeometry | None) -> dict[str, Any]:
        if geom is None:
            return _result("UNSUPPORTED", "Feature has no geometry")
        if geom.is_empty:
            return _result("INVALID", "Geometry is empty")

        geom_type = geom.geom_type
        if geom_type in POINT_TYPES:
            return _result("NOT_APPLICABLE", "Points have no area or length")
        if geom_type in AREA_TYPES:
            kind = "area"
        elif geom_type in LENGTH_TYPES:
            kind = "length"
        else:
            return _result("UNSUPPORTED", f"Measurement is not supported for {geom_type}")

        try:
            return self._measure(shapely.force_2d(geom), kind)
        except Exception as exc:  # never let one bad feature break the file
            return _result("INVALID", f"Measurement failed: {exc}")

    def _measure(self, geom: BaseGeometry, kind: str) -> dict[str, Any]:
        wgs = transform(self._to_wgs84.transform, geom) if self._to_wgs84 else geom
        minx, miny, maxx, maxy = wgs.bounds
        if not all(math.isfinite(v) for v in (minx, miny, maxx, maxy)) or not (
            -90 <= miny <= maxy <= 90 and -180 <= minx <= maxx <= 180
        ):
            return _result("INVALID", "Coordinates cannot be converted to valid longitude/latitude")

        projection = select_projection((minx, miny, maxx, maxy), kind)
        projected = transform(self._projector(projection.crs).transform, wgs)

        result = _result(
            "OK", projected_crs=projection.label, projection_strategy=projection.strategy
        )
        if not geom.is_valid:
            result["warnings"].append("Geometry is invalid (e.g. self-intersecting); result may be inaccurate")

        if kind == "area":
            area = projected.area
            result.update(
                area_sq_m=round(area, 3),
                area_hectares=round(area / 10_000, 6),
                perimeter_m=round(projected.length, 3),
                geodesic_check={"area_sq_m": round(_geodesic_area(wgs), 3)},
            )
        else:
            length = projected.length
            result.update(
                length_m=round(length, 3),
                length_km=round(length / 1000, 6),
                geodesic_check={"length_m": round(_geodesic_length(wgs), 3)},
            )
        return result

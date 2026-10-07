"""A small, dependency-light KML reader.

KML is always WGS84 lon/lat (EPSG:4326) by specification, so no CRS detection is
needed. We parse with defusedxml (protects against entity-expansion attacks) and
turn every <Placemark> into a feature. A malformed or unsupported Placemark never
fails the whole file: it is kept with an error message instead.
"""
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as SafeET
from pyproj import CRS
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.errors import InvalidFileError
from app.services.readers.base import ParsedDataset, ParsedFeature

WGS84 = CRS.from_epsg(4326)
# Geometry elements we recognise as "a geometry is present" (even if unsupported).
GEOMETRY_TAGS = {
    "Point", "LineString", "LinearRing", "Polygon", "MultiGeometry",
    "Model", "Track", "MultiTrack",
}


class UnsupportedGeometry(Exception):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: Element, name: str) -> list[Element]:
    return [c for c in el if _local(c.tag) == name]


def _first_text(el: Element, name: str) -> str | None:
    for c in _children(el, name):
        if c.text and c.text.strip():
            return c.text.strip()
    return None


def _coordinates(el: Element) -> list[tuple[float, float]]:
    node = next((n for n in el.iter() if _local(n.tag) == "coordinates"), None)
    if node is None or not (node.text or "").strip():
        raise ValueError("Missing <coordinates>")
    coords = []
    for token in node.text.split():
        parts = token.split(",")
        if len(parts) < 2:
            raise ValueError(f"Malformed coordinate tuple {token!r}")
        lon, lat = float(parts[0]), float(parts[1])  # altitude (if any) is ignored
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"Coordinate out of WGS84 range: {lon},{lat}")
        coords.append((lon, lat))
    return coords


def _parse_geometry(el: Element) -> BaseGeometry:
    tag = _local(el.tag)
    if tag == "Point":
        coords = _coordinates(el)
        if len(coords) != 1:
            raise ValueError("Point must have exactly one coordinate")
        return Point(coords[0])
    if tag in ("LineString", "LinearRing"):
        coords = _coordinates(el)
        if len(coords) < 2:
            raise ValueError("LineString needs at least 2 coordinates")
        return LineString(coords)
    if tag == "Polygon":
        outer = _children(el, "outerBoundaryIs")
        if not outer:
            raise ValueError("Polygon has no outerBoundaryIs")
        shell = _coordinates(outer[0])
        holes = [_coordinates(i) for i in _children(el, "innerBoundaryIs")]
        if len(shell) < 3 or any(len(h) < 3 for h in holes):
            raise ValueError("Polygon ring needs at least 3 coordinates")
        return Polygon(shell, holes)
    if tag == "MultiGeometry":
        parts: list[BaseGeometry] = []
        for child in el:
            if _local(child.tag) in GEOMETRY_TAGS:
                part = _parse_geometry(child)
                if part.geom_type in ("MultiPoint", "MultiLineString", "MultiPolygon"):
                    parts.extend(part.geoms)
                else:
                    parts.append(part)
        if not parts:
            raise ValueError("Empty MultiGeometry")
        kinds = {p.geom_type for p in parts}
        if kinds == {"Point"}:
            return MultiPoint(parts)
        if kinds == {"LineString"}:
            return MultiLineString(parts)
        if kinds == {"Polygon"}:
            return MultiPolygon(parts)
        return GeometryCollection(parts)
    raise UnsupportedGeometry(tag)


def _properties(placemark: Element) -> dict:
    props: dict = {}
    for key in ("name", "description"):
        value = _first_text(placemark, key)
        if value is not None:
            props[key] = value
    for node in placemark.iter():
        tag = _local(node.tag)
        if tag == "Data" and node.get("name"):
            props[node.get("name")] = _first_text(node, "value")
        elif tag == "SimpleData" and node.get("name"):
            props[node.get("name")] = (node.text or "").strip() or None
    return props


def read_kml(data: bytes, max_features: int) -> ParsedDataset:
    try:
        root = SafeET.fromstring(data)
    except (ParseError, ValueError) as exc:  # defusedxml errors subclass ValueError
        raise InvalidFileError(f"Not a valid KML/XML document: {exc}") from exc

    placemarks = [el for el in root.iter() if _local(el.tag) == "Placemark"]
    if len(placemarks) > max_features:
        raise InvalidFileError(f"File has more than {max_features} features")

    features: list[ParsedFeature] = []
    for index, pm in enumerate(placemarks):
        props = _properties(pm)
        geom_el = next((c for c in pm if _local(c.tag) in GEOMETRY_TAGS), None)
        if geom_el is None:
            features.append(ParsedFeature(index, None, props, "None", "Placemark has no geometry", "UNSUPPORTED"))
            continue
        try:
            features.append(ParsedFeature(index, _parse_geometry(geom_el), props))
        except UnsupportedGeometry as exc:
            kind = str(exc)
            features.append(ParsedFeature(index, None, props, kind, f"Unsupported KML geometry '{kind}'", "UNSUPPORTED"))
        except ValueError as exc:
            features.append(ParsedFeature(index, None, props, _local(geom_el.tag), f"Invalid geometry: {exc}", "INVALID"))

    if not placemarks:
        raise InvalidFileError("KML contains no Placemark elements")
    return ParsedDataset(crs=WGS84, features=features)

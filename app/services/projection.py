"""Choosing a projected CRS for measuring a geometry.

Strategy (per feature, based on its WGS84 bounding box):

* Normal case  -> the UTM zone of the bbox centre (EPSG:326xx north / 327xx south).
  UTM is conformal with <0.1% scale error inside its zone, which is the de-facto
  standard for survey-sized features.
* Fallback     -> a custom projection centred on the feature when UTM would be a
  poor fit (feature wider than one zone, or beyond UTM's 80S-84N validity):
    - area   : Lambert Azimuthal Equal-Area (area-preserving by construction)
    - length : Azimuthal Equidistant (distances from the centre are exact)
"""
from dataclasses import dataclass

UTM_MAX_LON_SPAN = 6.0
UTM_MIN_LAT, UTM_MAX_LAT = -80.0, 84.0


@dataclass(frozen=True)
class Projection:
    crs: str  # anything pyproj accepts: "EPSG:32643" or a PROJ string
    label: str
    strategy: str


def select_projection(bounds: tuple[float, float, float, float], kind: str) -> Projection:
    """`bounds` are WGS84 (minx, miny, maxx, maxy); `kind` is 'area' or 'length'."""
    minx, miny, maxx, maxy = bounds
    lon, lat = (minx + maxx) / 2, (miny + maxy) / 2

    fits_utm = (maxx - minx) <= UTM_MAX_LON_SPAN and miny >= UTM_MIN_LAT and maxy <= UTM_MAX_LAT
    if fits_utm:
        zone = min(max(int((lon + 180) // 6) + 1, 1), 60)
        epsg = (32600 if lat >= 0 else 32700) + zone
        return Projection(f"EPSG:{epsg}", f"EPSG:{epsg}", "utm")

    if kind == "area":
        proj, name = "laea", "Lambert Azimuthal Equal-Area"
    else:
        proj, name = "aeqd", "Azimuthal Equidistant"
    crs = f"+proj={proj} +lat_0={lat:.6f} +lon_0={lon:.6f} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    return Projection(crs, f"{name} (lat_0={lat:.4f}, lon_0={lon:.4f})", f"custom_{proj}")

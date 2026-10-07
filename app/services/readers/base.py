"""Format-independent data structures and helpers shared by all readers."""
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry.base import BaseGeometry


@dataclass
class ParsedFeature:
    index: int
    geometry: BaseGeometry | None
    properties: dict[str, Any] = field(default_factory=dict)
    # Used when `geometry` is None (e.g. an unsupported KML geometry kind).
    geometry_type: str | None = None
    # A per-feature problem; the feature is kept and reported, not dropped.
    error: str | None = None
    error_status: str = "INVALID"  # or "UNSUPPORTED"


@dataclass
class ParsedDataset:
    crs: CRS
    features: list[ParsedFeature]


def crs_label(crs: CRS) -> str:
    """'EPSG:4326' when the CRS has an authority code, otherwise its name."""
    authority = crs.to_authority(min_confidence=70)
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.name


def json_safe(value: Any) -> Any:
    """Convert attribute values (numpy, pandas, datetime, NaN...) to JSON-safe types."""
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)

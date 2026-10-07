# Geospatial File Measurement API

A FastAPI backend that accepts a **KML** file or a **zipped Shapefile**, extracts every feature
(geometry, CRS, attributes) and returns **area** (polygons) and **length** (lines), computed in a
properly chosen **projected CRS** – never in degrees.

## Setup

Requires Python 3.10+ (tested on 3.12). GeoPandas/pyogrio/pyproj ship binary wheels, so no system GDAL is needed.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

* Interactive docs (Swagger UI): <http://localhost:8000/docs>
* Run tests: `pytest`
* Docker: `docker build -t geo-measure . && docker run -p 8000:8000 -v geo-data:/data geo-measure`

Configuration (environment variables, all optional):

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./geo_measure.db` | Any SQLAlchemy URL (e.g. PostgreSQL) |
| `MAX_UPLOAD_MB` | `50` | Max upload size |
| `MAX_UNZIPPED_MB` | `500` | Zip-bomb protection |
| `MAX_ZIP_MEMBERS` | `200` | Max files inside a zip |
| `MAX_FEATURES` | `100000` | Max features per file |

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/files/` | Upload + process a `.kml` or `.zip` (Shapefile) |
| GET | `/api/files/{id}/` | File information |
| GET | `/api/files/{id}/measurements/` | Per-feature measurements + totals (`?limit=&offset=`) |
| GET | `/api/files/{id}/features/` | Extracted features: geometry (GeoJSON), CRS, properties (`?limit=&offset=`) |
| GET | `/health` | Liveness check |

A sample file is in `samples/survey.kml`.

### Upload

```bash
curl -F "file=@samples/survey.kml" http://localhost:8000/api/files/
```
```json
{
  "id": "ab7ceedc29e94ba19d43585f8a115e50",
  "filename": "survey.kml",
  "feature_count": 4,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null,
  "geometry_types": {"Polygon": 1, "LineString": 1, "Point": 1, "Model": 1},
  "created_at": "2026-10-07T08:37:34.572551Z"
}
```

Errors: `415` unsupported extension · `413` too large · `400` empty file ·
`422` content can't be parsed (the file is still recorded with `status: "FAILED"` and an `error`; the 422 body contains
`{"detail": "...", "file": {...}}` so `GET /api/files/{id}/` works for it).

### Measurements

```bash
curl http://localhost:8000/api/files/ab7ceedc29e94ba19d43585f8a115e50/measurements/
```
```json
{
  "file_id": "ab7c...", "total": 4, "limit": 100, "offset": 0,
  "summary": {
    "total_area_sq_m": 1184397.274,
    "total_length_m": 6290.869,
    "by_status": {"OK": 2, "NOT_APPLICABLE": 1, "UNSUPPORTED": 1}
  },
  "items": [
    {
      "index": 0, "geometry_type": "Polygon", "crs": "EPSG:4326",
      "measurement": {
        "status": "OK",
        "area_sq_m": 1184397.274, "area_hectares": 118.439727, "perimeter_m": 4353.778,
        "projected_crs": "EPSG:32643", "projection_strategy": "utm",
        "geodesic_check": {"area_sq_m": 1185262.983},
        "warnings": []
      }
    },
    {
      "index": 1, "geometry_type": "LineString", "crs": "EPSG:4326",
      "measurement": {
        "status": "OK", "length_m": 6290.869, "length_km": 6.290869,
        "projected_crs": "EPSG:32643", "projection_strategy": "utm",
        "geodesic_check": {"length_m": 6293.183}
      }
    },
    {"index": 2, "geometry_type": "Point", "crs": "EPSG:4326",
     "measurement": {"status": "NOT_APPLICABLE", "message": "Points have no area or length"}},
    {"index": 3, "geometry_type": "Model", "crs": "EPSG:4326",
     "measurement": {"status": "UNSUPPORTED", "message": "Unsupported KML geometry 'Model'"}}
  ]
}
```
(Null fields trimmed for readability.)

**Measurement `status` values**

| Status | Meaning |
|---|---|
| `OK` | Measured |
| `NOT_APPLICABLE` | Point / MultiPoint – nothing to measure |
| `UNSUPPORTED` | No geometry, GeometryCollection, or an unsupported KML kind (`Model`, `gx:Track`…) |
| `INVALID` | Malformed / out-of-range coordinates, empty geometry |

One bad feature never fails the file; it gets a status and a message.

### Features

```bash
curl http://localhost:8000/api/files/{id}/features/
```
```json
{"items": [{"index": 0, "geometry_type": "Polygon", "crs": "EPSG:4326",
            "geometry": {"type": "Polygon", "coordinates": [[[74.5, 15.85, 0.0], "..."]]},
            "properties": {"name": "Plot A", "owner": "Ravi"}}]}
```
Geometry is returned as GeoJSON **in the file's original CRS**.

## Architecture

```
app/
├── main.py              # FastAPI app, lifespan creates tables
├── config.py            # env-based settings
├── database.py, models.py   # SQLAlchemy 2.0: UploadedFile 1──* Feature
├── schemas.py           # Pydantic response models (drive the OpenAPI docs)
├── api/files.py         # HTTP layer only: validation, streaming upload, pagination
└── services/
    ├── readers/         # format-specific parsing -> common ParsedDataset
    │   ├── kml.py       #   defusedxml-based KML parser
    │   └── shapefile.py #   safe unzip + GeoPandas/pyogrio
    ├── projection.py    # picks the projected CRS
    ├── measurements.py  # Measurer: transform + area/length
    └── processor.py     # orchestrates read -> measure -> persist
```

**File-processing flow**
1. Route validates extension, streams the upload to a temp file with a size cap.
2. `processor.process_upload` creates a `files` row (`PROCESSING`) and picks a reader.
3. The reader returns `ParsedDataset(crs, features[])` where each `ParsedFeature` has geometry, properties and an optional per-feature error.
   Shapefile: zip is extracted safely (zip-slip, zip-bomb, `__MACOSX` junk handled), exactly one `.shp` required, CRS read from `.prj`.
   KML: Placemarks parsed into Point / LineString / Polygon (with holes) / Multi*; `ExtendedData` → properties.
4. Each feature is measured, then all rows are bulk-inserted. The file becomes `COMPLETED` (or `FAILED` with an error message).

**Measurement flow** (`Measurer.measure`)
`geometry → drop Z → WGS84 (for choosing a projection) → projected CRS → shapely .area / .length`.
Type dispatch: Polygon/MultiPolygon → area (+ hectares, perimeter); LineString/LinearRing/MultiLineString → length;
Point/MultiPoint → `NOT_APPLICABLE`; anything else → `UNSUPPORTED`. Measurements are computed once at upload and stored,
so GET endpoints are cheap reads.

**CRS handling**
* KML is always EPSG:4326 by spec. Shapefile CRS comes from `.prj` (rejected with a clear error if missing).
* Projection is chosen **per feature** from its WGS84 bounding box (`services/projection.py`):
  * default: the **UTM zone** of the bbox centre (EPSG:326xx / 327xx);
  * fallback for features wider than one zone (>6°) or outside 80°S–84°N: a **custom Lambert Azimuthal Equal-Area**
    (areas) or **Azimuthal Equidistant** (lengths) centred on the feature.
* This also fixes already-projected inputs with distorting CRSs: a Web Mercator shapefile is reprojected rather than measured as-is (covered by a test).
* Every result reports the CRS used (`projected_crs`, `projection_strategy`).
* `geodesic_check` is an independent ellipsoidal calculation (pyproj `Geod`) on the WGS84 geometry. It is a built-in sanity
  check; for survey-sized features it agrees with the projected value to ~0.1%.

## Design Decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| **FastAPI** | Typed models, free OpenAPI docs, simple for an API-only service | Django+DRF (heavier; better if I needed admin/auth) |
| **Per-feature local projection** | A file may span regions; one CRS for all would distort. UTM is the standard for local metric work | One CRS per file (simpler, worse for large/mixed files); pure geodesic (accurate, but the brief asks for projected CRS – kept as a cross-check) |
| **Custom equal-area / equidistant fallback** | UTM breaks down for very wide or polar features | Always use a world equal-area CRS (EPSG:6933) – less accurate locally |
| **Hand-written KML parser** | GDAL's KML driver availability varies by build; parser is ~100 lines, no native dependency, and exposes per-Placemark errors | `fastkml`, `pyogrio` KML driver |
| **GeoPandas/pyogrio for Shapefile** | Robust, handles encodings and CRS from `.prj` | `pyshp` + manual CRS parsing |
| **Synchronous processing** | Simple, deterministic; the response already contains the final status. Bounded by `MAX_FEATURES`/`MAX_UPLOAD_MB` | Celery/RQ background jobs (see Future scope) |
| **Persist features and measurements in SQLite/SQLAlchemy** | Makes GET endpoints cheap, supports pagination; swap to PostgreSQL via `DATABASE_URL` | Keeping uploaded file and recomputing on each request |
| **Per-feature status instead of failing the file** | Real-world files contain junk features; users still want the good ones | Rejecting the whole upload |
| **Security hardening on uploads** | zip-slip, zip-bomb, XML entity expansion (defusedxml), size caps, only whitelisted shapefile extensions extracted | – |
| **Shapefile without `.prj` rejected** | Guessing a CRS silently produces wrong areas | Assume EPSG:4326 (dangerous) |

**Known limitations**
* Polygon edges are straight lines *in the projected CRS*. For very large polygons (many degrees across) this differs
  from geodesic edges – the reason the geodesic check can drift on continent-scale shapes.
* Features crossing the antimeridian are not handled specially.
* `GeometryCollection` / mixed KML `MultiGeometry` is reported as `UNSUPPORTED` rather than summed.
* Only one shapefile per zip; `.kmz` is not accepted.

## Learnings

* A lat/lon polygon's "area" in degrees is meaningless – and even *projected* data isn't safe: Web Mercator inflates areas ~4× at 60°N, so
  the source CRS can't be trusted to be measurement-friendly.
* Projected straight-line edges vs. geodesic edges is a real accuracy trade-off, which is why I kept a geodesic cross-check
  instead of treating either as ground truth.
* Shapefile pitfalls: one geometry type per file, missing `.prj`, NaN in DBF attributes (not JSON serialisable), and hostile zips.
* pyproj `Transformer` objects aren't guaranteed thread-safe, so they're cached per request rather than globally.
* FastAPI runs sync endpoints in a threadpool, which is the right fit for CPU/IO-bound GDAL work.

## Future Scope

* **Async processing**: queue (Celery/RQ/arq) for large files, `PROCESSING` status polling or webhooks; the `status` field and the processor are already shaped for this.
* More formats: **KMZ, GeoJSON, GeoPackage, GPX**; multi-layer files; multiple shapefiles per zip.
* Geodesic edge densification (segmentize before projecting) for very large polygons; antimeridian/polar handling.
* Optional units (acres, miles), user-selectable measurement CRS or method per request.
* Auth, per-user ownership, rate limiting, file retention/cleanup, object storage (S3) for originals.
* Alembic migrations, PostgreSQL + PostGIS for spatial queries, Prometheus metrics/structured logging.
* CI (GitHub Actions: pytest + ruff + mypy), property-based tests, larger fixture set from real survey data.
* Streaming/ chunked feature persistence to cap memory on huge files.

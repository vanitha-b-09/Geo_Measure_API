import io
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from tests.helpers import KML, shapefile_zip


def upload(client, name, data, ctype="application/octet-stream"):
    return client.post("/api/files/", files={"file": (name, data, ctype)})


def measurements(client, file_id):
    return client.get(f"/api/files/{file_id}/measurements/").json()


# ---------------------------------------------------------------- KML
def test_kml_end_to_end(client):
    r = upload(client, "survey.kml", KML)
    assert r.status_code == 201
    info = r.json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 7
    assert info["crs"] == "EPSG:4326"
    assert info["filename"] == "survey.kml"
    assert client.get(f"/api/files/{info['id']}/").json()["id"] == info["id"]

    items = {i["index"]: i for i in measurements(client, info["id"])["items"]}

    plot = items[0]["measurement"]
    assert items[0]["geometry_type"] == "Polygon"
    assert plot["status"] == "OK" and plot["projected_crs"] == "EPSG:32643"
    assert plot["area_sq_m"] == pytest.approx(plot["geodesic_check"]["area_sq_m"], rel=2e-3)
    assert 1.1e6 < plot["area_sq_m"] < 1.25e6  # ~1.07 km x ~1.1 km

    road = items[1]["measurement"]
    assert road["length_m"] == pytest.approx(110_600, rel=3e-3)  # ~1 degree of latitude
    assert road["length_m"] == pytest.approx(road["geodesic_check"]["length_m"], rel=2e-3)

    assert items[2]["measurement"]["status"] == "NOT_APPLICABLE"   # Point
    assert items[3]["measurement"]["status"] == "UNSUPPORTED"      # <Model>
    assert items[4]["measurement"]["status"] == "UNSUPPORTED"      # no geometry
    assert items[5]["measurement"]["status"] == "INVALID"          # out-of-range coords
    assert items[6]["measurement"]["status"] == "UNSUPPORTED"      # GeometryCollection


def test_kml_features_endpoint_returns_properties_and_geometry(client):
    fid = upload(client, "s.kml", KML).json()["id"]
    first = client.get(f"/api/files/{fid}/features/").json()["items"][0]
    assert first["properties"] == {"name": "Plot A", "owner": "Ravi"}
    assert first["geometry"]["type"] == "Polygon"
    assert first["crs"] == "EPSG:4326"


def test_measurement_pagination_and_summary(client):
    fid = upload(client, "s.kml", KML).json()["id"]
    body = client.get(f"/api/files/{fid}/measurements/?limit=2&offset=1").json()
    assert body["total"] == 7 and len(body["items"]) == 2 and body["items"][0]["index"] == 1
    assert body["summary"]["by_status"]["OK"] == 2
    assert body["summary"]["total_area_sq_m"] > 0


# ---------------------------------------------------------------- Shapefile
def test_projected_shapefile_exact_area(client, tmp_path):
    # 100 m x 100 m square in UTM 43N -> exactly 10,000 m2
    gdf = gpd.GeoDataFrame(
        {"plot": ["A", "B"], "val": [1.5, float("nan")]},
        geometry=[box(500000, 1750000, 500100, 1750100), box(500200, 1750000, 500400, 1750100)],
        crs="EPSG:32643",
    )
    r = upload(client, "plots.zip", shapefile_zip(gdf, tmp_path))
    assert r.status_code == 201 and r.json()["crs"] == "EPSG:32643"
    fid = r.json()["id"]
    m = measurements(client, fid)["items"]
    assert m[0]["measurement"]["area_sq_m"] == pytest.approx(10_000, rel=1e-5)
    assert m[1]["measurement"]["area_sq_m"] == pytest.approx(20_000, rel=1e-5)
    props = client.get(f"/api/files/{fid}/features/").json()["items"][1]["properties"]
    assert props == {"plot": "B", "val": None}  # NaN -> null


def test_projected_line_shapefile_length(client, tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[LineString([(500000, 1750000), (500300, 1750400)])], crs="EPSG:32643")
    fid = upload(client, "roads.zip", shapefile_zip(gdf, tmp_path)).json()["id"]
    m = measurements(client, fid)["items"][0]["measurement"]
    assert m["length_m"] == pytest.approx(500, rel=1e-5)


def test_geographic_shapefile_is_not_measured_in_degrees(client, tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[box(74.5, 15.85, 74.51, 15.86)], crs="EPSG:4326")
    fid = upload(client, "geo.zip", shapefile_zip(gdf, tmp_path)).json()["id"]
    first = measurements(client, fid)["items"][0]["measurement"]
    assert first["area_sq_m"] > 1e6  # would be 1e-4 if computed in degrees
    assert first["area_sq_m"] == pytest.approx(first["geodesic_check"]["area_sq_m"], rel=2e-3)


def test_web_mercator_shapefile_is_corrected(client, tmp_path):
    # Web Mercator inflates areas at 60N by ~4x; we must reproject first.
    g = gpd.GeoDataFrame(geometry=[box(10, 60, 10.01, 60.01)], crs="EPSG:4326").to_crs("EPSG:3857")
    fid = upload(client, "merc.zip", shapefile_zip(g, tmp_path)).json()["id"]
    m = measurements(client, fid)["items"][0]["measurement"]
    assert m["area_sq_m"] == pytest.approx(m["geodesic_check"]["area_sq_m"], rel=3e-3)


def test_wide_feature_uses_equal_area_fallback(client, tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[box(-20, -10, 40, 30)], crs="EPSG:4326")  # 60 degrees wide
    fid = upload(client, "wide.zip", shapefile_zip(gdf, tmp_path)).json()["id"]
    m = measurements(client, fid)["items"][0]["measurement"]
    assert m["projection_strategy"] == "custom_laea"
    # Straight edges in the projection differ from geodesic edges at this scale, so only
    # check plausibility (a 60x40 degree lat/lon box is roughly 2.8-3.1e13 m2).
    assert 2.7e13 < m["area_sq_m"] < 3.2e13


# ---------------------------------------------------------------- Errors
def test_unsupported_extension(client):
    assert upload(client, "a.txt", b"hello").status_code == 415


def test_empty_file(client):
    assert upload(client, "a.kml", b"").status_code == 400


def test_invalid_kml_returns_422_and_failed_record(client):
    r = upload(client, "bad.kml", "<kml><oops>")
    assert r.status_code == 422
    fid = r.json()["file"]["id"]
    info = client.get(f"/api/files/{fid}/").json()
    assert info["status"] == "FAILED" and info["error"]


def test_zip_without_shapefile(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "nope")
    r = upload(client, "x.zip", buf.getvalue())
    assert r.status_code == 422 and ".shp" in r.json()["detail"]


def test_not_a_zip(client):
    assert upload(client, "x.zip", b"not a zip").status_code == 422


def test_zip_slip_is_rejected(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.shp", "x")
    r = upload(client, "evil.zip", buf.getvalue())
    assert r.status_code == 422 and "unsafe" in r.json()["detail"]


def test_shapefile_without_prj_is_rejected(client, tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[Point(1, 1)], crs="EPSG:4326")
    data = shapefile_zip(gdf, tmp_path)
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in src.namelist():
            if not n.endswith(".prj"):
                zf.writestr(n, src.read(n))
    r = upload(client, "noprj.zip", buf.getvalue())
    assert r.status_code == 422 and "CRS" in r.json()["detail"]


def test_unknown_file_404(client):
    assert client.get("/api/files/nope/").status_code == 404
    assert client.get("/api/files/nope/measurements/").status_code == 404

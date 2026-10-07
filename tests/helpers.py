import io
import zipfile
from pathlib import Path

import geopandas as gpd

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>Plot A</name>
  <ExtendedData><Data name="owner"><value>Ravi</value></Data></ExtendedData>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>
    74.50,15.85,0 74.51,15.85,0 74.51,15.86,0 74.50,15.86,0 74.50,15.85,0
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Road</name><LineString><coordinates>77,10 77,11</coordinates></LineString></Placemark>
<Placemark><name>Well</name><Point><coordinates>74.5,15.9</coordinates></Point></Placemark>
<Placemark><name>Track</name><Model/></Placemark>
<Placemark><name>Empty</name></Placemark>
<Placemark><name>Bad</name><LineString><coordinates>200,95 1,1</coordinates></LineString></Placemark>
<Placemark><name>Mixed</name><MultiGeometry>
  <Point><coordinates>1,1</coordinates></Point>
  <LineString><coordinates>1,1 2,2</coordinates></LineString></MultiGeometry></Placemark>
</Document></kml>"""


def shapefile_zip(gdf: gpd.GeoDataFrame, tmp_path: Path) -> bytes:
    folder = tmp_path / "shp"
    folder.mkdir(exist_ok=True)
    gdf.to_file(folder / "data.shp", driver="ESRI Shapefile")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in folder.iterdir():
            zf.write(p, p.name)
    return buf.getvalue()

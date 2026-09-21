import math
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.apps.routing.constants import EDGES_TABLE, SRID


class NearestEdgeRequest(BaseModel):
    lon: float = Field(..., ge=-180, le=180)
    lat: float = Field(..., ge=-90, le=90)
    zoom: int = Field(14, ge=0, le=22)


class NearestEdgeResponse(BaseModel):
    edge_id: int
    distance_m: float
    threshold_m: float
    accepted: bool
    zoom: int
    density_avg_m: Optional[float] = None
    geometry_wkt: Optional[str] = None
    geometry_geojson: Optional[str] = None


def _meters_per_pixel(lat: float, zoom: int) -> float:
    # WebMercator approx: meters per pixel at latitude
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


def _compute_threshold_m(lat: float, zoom: int, density_avg_m: Optional[float]) -> float:
    mpp = _meters_per_pixel(lat, zoom)

    # tolérance visuelle (px)
    base_px = 18.0

    # densité: avg_m ~ 25m => facteur 1.0
    avg_m = density_avg_m if (density_avg_m is not None and density_avg_m > 0) else 25.0
    density_factor = max(0.70, min(avg_m / 25.0, 1.60))

    threshold = base_px * mpp * density_factor

    # clamp sécurité
    threshold = max(12.0, min(threshold, 180.0))
    return float(threshold)


def nearest_edge_smart(db: Session, lon: float, lat: float, zoom: int) -> dict:
    q = text(f"""
      WITH p AS (
        SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), {SRID}) AS pt
      ),
      c AS (
        SELECT
          e.id,
          ST_LineMerge(e.geom_way) AS g
        FROM {EDGES_TABLE} e
        ORDER BY e.geom_way <-> (SELECT pt FROM p)
        LIMIT 10
      ),
      d AS (
        SELECT
          id AS edge_id,
          ST_Distance(g::geography, (SELECT pt FROM p)::geography) AS dist_m,
          ST_AsText(g) AS wkt,
          ST_AsGeoJSON(g) AS geojson
        FROM c
      ),
      stats AS (
        SELECT AVG(dist_m) AS avg_m
        FROM d
      )
      SELECT
        (SELECT avg_m FROM stats) AS density_avg_m,
        edge_id,
        dist_m,
        wkt,
        geojson
      FROM d
      ORDER BY dist_m
      LIMIT 1
    """)

    row = db.execute(q, {"lon": lon, "lat": lat}).mappings().one()

    distance_m = float(row["dist_m"])
    density_avg_m = float(row["density_avg_m"]) if row["density_avg_m"] is not None else None
    threshold_m = _compute_threshold_m(lat=lat, zoom=zoom, density_avg_m=density_avg_m)

    return {
        "edge_id": int(row["edge_id"]),
        "distance_m": distance_m,
        "threshold_m": threshold_m,
        "accepted": distance_m <= threshold_m,
        "zoom": int(zoom),
        "density_avg_m": density_avg_m,
        "geometry_wkt": row["wkt"],
        "geometry_geojson": row["geojson"],
    }

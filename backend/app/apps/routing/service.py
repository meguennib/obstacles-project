import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.apps.routing.schemas import RouteRequest, RouteResponse, LatLng
from app.apps.routing.constants import EDGES_TABLE, SRID

logger = logging.getLogger("routing")


@dataclass(frozen=True)
class BBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def to_sql(self) -> str:
        return f"ST_MakeEnvelope({self.min_lon}, {self.min_lat}, {self.max_lon}, {self.max_lat}, {SRID})"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(x, hi))


def compute_bbox(points: List[LatLng], margin_factor: float, min_margin: float, max_margin: float) -> BBox:
    lons = [p.lon for p in points]
    lats = [p.lat for p in points]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    diag = max(max_lon - min_lon, max_lat - min_lat)
    margin = max(min_margin, diag * margin_factor)
    margin = min(margin, max_margin)

    return BBox(
        min_lon=_clamp(min_lon - margin, -180, 180),
        max_lon=_clamp(max_lon + margin, -180, 180),
        min_lat=_clamp(min_lat - margin, -90, 90),
        max_lat=_clamp(max_lat + margin, -90, 90),
    )


def edges_sql_excluding_closures(bbox: Optional[BBox] = None) -> str:
    where = []
    if bbox is not None:
        where.append(f"e.geom_way && {bbox.to_sql()}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    return f"""
      WITH closed AS (
        SELECT edge_id
        FROM public.events_road_closed
        WHERE status='validated'
          AND edge_id IS NOT NULL
          AND now() BETWEEN start_time AND end_time
      )
      SELECT
        e.id,
        e.source,
        e.target,
        CASE
          WHEN c.edge_id IS NOT NULL THEN -1
          ELSE COALESCE(e.dynamic_cost, e.cost)
        END AS cost,
        CASE
          WHEN c.edge_id IS NOT NULL THEN -1
          ELSE COALESCE(e.dynamic_reverse_cost, e.reverse_cost, e.dynamic_cost, e.cost)
        END AS reverse_cost
      FROM {EDGES_TABLE} e
      LEFT JOIN closed c ON c.edge_id = e.id
      {where_sql}
    """


def nearest_graph_node_id(db: Session, lon: float, lat: float) -> int:
    """
    ✅ Le plus sûr :
    on cherche l’edge le plus proche (KNN sur geom_way), puis on choisit
    l’endpoint (source/target) le plus proche du clic.
    => node_id est garanti présent dans le graphe pgr_dijkstra (source/target).
    """
    q = text(f"""
      WITH p AS (
        SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), {SRID}) AS pt
      ),
      c AS (
        SELECT id, source, target, x1, y1, x2, y2, geom_way
        FROM {EDGES_TABLE}
        ORDER BY geom_way <-> (SELECT pt FROM p)
        LIMIT 80
      ),
      endpoints AS (
        SELECT
          source AS node_id,
          ST_Distance(
            ST_SetSRID(ST_MakePoint(x1, y1), {SRID})::geography,
            (SELECT pt FROM p)::geography
          ) AS d
        FROM c
        UNION ALL
        SELECT
          target AS node_id,
          ST_Distance(
            ST_SetSRID(ST_MakePoint(x2, y2), {SRID})::geography,
            (SELECT pt FROM p)::geography
          ) AS d
        FROM c
      )
      SELECT node_id
      FROM endpoints
      WHERE node_id IS NOT NULL
      ORDER BY d
      LIMIT 1
    """)
    node = db.execute(q, {"lon": lon, "lat": lat}).scalar_one()
    return int(node)


def dijkstra_edges(db: Session, source: int, target: int, bbox: Optional[BBox]) -> List[int]:
    edges_sql = edges_sql_excluding_closures(bbox)
    q = text(f"""
      SELECT edge
      FROM pgr_dijkstra(
        $$ {edges_sql} $$,
        :source,
        :target,
        directed := true
      )
      WHERE edge <> -1
    """)
    rows = db.execute(q, {"source": source, "target": target}).scalars().all()
    return [int(e) for e in rows]


def summarize_route(db: Session, edge_ids: List[int]) -> Tuple[float, float, Optional[str]]:
    if not edge_ids:
        # 0 distance, empty geometry
        return 0.0, 0.0, None

    # ✅ CORRECTION: Utiliser UNNEST avec ORDINALITY pour garantir l'ordre des segments
    # Sinon `WHERE id = ANY(...)` mélange les segments et ST_LineMerge peut échouer ou faire n'importe quoi.
    q = text(f"""
      SELECT
        COALESCE(SUM(e.km), 0)::float8 AS distance_km,
        COALESCE(SUM(CASE WHEN e.kmh > 0 THEN (e.km / e.kmh) * 60 ELSE 0 END), 0)::float8 AS duration_min,
        ST_AsGeoJSON(ST_MakeLine(e.geom_way ORDER BY t.ord)) AS geojson
      FROM unnest(:edge_ids) WITH ORDINALITY AS t(id, ord)
      JOIN {EDGES_TABLE} e ON e.id = t.id
    """)
    row = db.execute(q, {"edge_ids": edge_ids}).mappings().one()
    return float(row["distance_km"]), float(row["duration_min"]), row["geojson"]


def compute_route(db: Session, req: RouteRequest) -> RouteResponse:
    points: List[LatLng] = [req.start] + (req.vias or []) + [req.end]
    
    # On récupère les IDs des noeuds du graphe les plus proches
    node_ids = [nearest_graph_node_id(db, p.lon, p.lat) for p in points]

    bbox_trials: List[Optional[BBox]] = [
        compute_bbox(points, margin_factor=0.25, min_margin=0.02, max_margin=0.50),
        compute_bbox(points, margin_factor=0.50, min_margin=0.04, max_margin=1.00),
        compute_bbox(points, margin_factor=1.00, min_margin=0.08, max_margin=2.00),
        None,  # full graph fallback
    ]

    all_edges: List[int] = []

    for a, b in zip(node_ids, node_ids[1:]):
        if a == b:
            # Même noeud de départ et d'arrivée, distance 0, on skip
            continue

        seg_edges: List[int] = []
        for i, bbox in enumerate(bbox_trials):
            seg_edges = dijkstra_edges(db, a, b, bbox=bbox)
            if seg_edges:
                if i > 0:
                    logger.warning("bbox expansion used: trial=%s bbox=%s", i, "NONE(full)" if bbox is None else bbox)
                break
        
        if not seg_edges:
            # Si on n'a rien trouvé entre 2 points distincts -> échec
            raise ValueError(f"No path found between node {a} and {b} (graph disconnected or closures block the route).")

        all_edges.extend(seg_edges)

    distance_km, duration_min, geojson = summarize_route(db, all_edges)

    return RouteResponse(
        distance_km=round(distance_km, 3),
        duration_min=round(duration_min, 1),
        edges=all_edges,
        geometry_geojson=geojson,
    )

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.apps.routing.schemas import RouteRequest, RouteResponse, LatLng, SnappedPoint
from app.apps.routing.constants import EDGES_TABLE, SRID
from app.apps.routing.costs import build_cost_expr, get_v_cap
from app.core.config import settings

logger = logging.getLogger("routing")


# =====================================================================
# Géométrie / BBox
# =====================================================================

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


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distance grand cercle en km."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def utm_zone_srid(mid_lon: float) -> int:
    """Zone UTM nord (EPSG:32601..32660) contenant mid_lon.

    Algérie: 32629 / 32630 / 32631 / 32632.
    La projection UTM (distorsion < 0.5 % en zone) rend l'heuristique A*
    quasi admissible: la distance euclidienne projetée ≈ distance réelle.
    """
    zone = int((mid_lon + 186.0) // 6)
    zone = max(1, min(60, zone))
    return 32600 + zone


# =====================================================================
# SQL des edges avec exclusion des obstacles
# =====================================================================

def closed_cte() -> str:
    """CTE des obstacles actifs à `now()`.

    v1.2:
      - MULTI_EDGE_CLOSURES=true  -> event_edge_closure (fermetures multi-edges,
        sens, pénalité, end_time nullable)
      - MULTI_EDGE_CLOSURES=false -> events_road_closed.edge_id (comportement d'origine)
    """
    time_filter = "now() >= start_time AND (end_time IS NULL OR now() <= end_time)"
    if settings.multi_edge_closures:
        return (
            "WITH closed AS (\n"
            "  SELECT edge_id, direction, mode, penalty_factor\n"
            "  FROM public.event_edge_closure\n"
            "  WHERE status = 'validated'\n"
            f"    AND {time_filter}\n"
            ")"
        )
    return (
        "WITH closed AS (\n"
        "  SELECT edge_id,\n"
        "         COALESCE(direction, 'both') AS direction,\n"
        "         COALESCE(mode, 'block') AS mode,\n"
        "         COALESCE(penalty_factor, 5) AS penalty_factor\n"
        "  FROM public.events_road_closed\n"
        "  WHERE status = 'validated'\n"
        "    AND edge_id IS NOT NULL\n"
        f"    AND {time_filter}\n"
        ")"
    )


def _cost_columns(alias: str = "e") -> Tuple[str, str]:
    """Colonnes cost / reverse_cost avec gestion des obstacles:
      - mode=block:    -1 sur le(s) sens fermés (pgRouting: edge retiré)
      - mode=penalty:  coût × penalty_factor (évitement doux)
      - direction: both / forward (source->target) / reverse
    """
    base_f = build_cost_expr("cost", alias)
    base_r = build_cost_expr("reverse_cost", alias)
    cost_sql = (
        "CASE\n"
        "  WHEN c.edge_id IS NOT NULL AND c.mode = 'block' AND c.direction IN ('both', 'forward') THEN -1\n"
        f"  WHEN c.edge_id IS NOT NULL AND c.mode = 'penalty' AND c.direction IN ('both', 'forward') THEN {base_f} * c.penalty_factor\n"
        f"  ELSE {base_f}\n"
        "END AS cost"
    )
    reverse_sql = (
        "CASE\n"
        "  WHEN c.edge_id IS NOT NULL AND c.mode = 'block' AND c.direction IN ('both', 'reverse') THEN -1\n"
        f"  WHEN c.edge_id IS NOT NULL AND c.mode = 'penalty' AND c.direction IN ('both', 'reverse') THEN {base_r} * c.penalty_factor\n"
        f"  ELSE {base_r}\n"
        "END AS reverse_cost"
    )
    return cost_sql, reverse_sql


def edges_sql_excluding_closures(bbox: Optional[BBox] = None, with_geom: bool = False) -> str:
    """Sous-requête SQL utilisée comme "table d'edges" de pgr_dijkstra / pgr_astar."""
    where = []
    if bbox is not None:
        where.append(f"e.geom_way && {bbox.to_sql()}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cost_sql, reverse_sql = _cost_columns("e")
    geom_sel = "e.geom_way, e.x1, e.y1, e.x2, e.y2, " if with_geom else ""

    return f"""
      {closed_cte()}
      SELECT
        e.id,
        e.source,
        e.target,
        {geom_sel}
        {cost_sql},
        {reverse_sql}
      FROM {EDGES_TABLE} e
      LEFT JOIN closed c ON c.edge_id = e.id
      {where_sql}
    """


# =====================================================================
# Snap des points au graphe (batché, sens de voyage)
# =====================================================================

@dataclass(frozen=True)
class SnappedNode:
    node_id: int
    lon: float
    lat: float
    dist_m: float

# Nombre d'edges KNN par point (inchangé depuis l'origine: 80).
KNN_EDGES = 80
# Nombre d'edges KNN dont on garde les endpoints pour la sélection directionnelle.
KNN_CANDIDATE_EDGES = 8


def _travel_direction(points: List[LatLng], i: int) -> Tuple[float, float]:
    """Vecteur de voyage (degrés) au point i: avant au départ, arrière à l'arrivée."""
    n = len(points)
    if n < 2:
        return 0.0, 0.0
    if i == 0:
        return points[1].lon - points[0].lon, points[1].lat - points[0].lat
    if i == n - 1:
        return points[-1].lon - points[-2].lon, points[-1].lat - points[-2].lat
    return points[i + 1].lon - points[i - 1].lon, points[i + 1].lat - points[i - 1].lat


def snap_sql() -> str:
    """SQL du snap batché (pur — testable sans DB). Paramètres: :lons, :lats."""
    return f"""
      WITH pts AS (
        SELECT idx - 1 AS idx0, lon, lat,
               ST_SetSRID(ST_MakePoint(lon, lat), {SRID}) AS pt
        FROM unnest(CAST(:lons AS float8[]), CAST(:lats AS float8[]))
             WITH ORDINALITY AS p(lon, lat, idx)
      ),
      c AS (
        SELECT p.idx0, e.id, e.source, e.target, e.x1, e.y1, e.x2, e.y2, e.geom_way,
               ROW_NUMBER() OVER (PARTITION BY p.idx0 ORDER BY e.geom_way <-> p.pt) AS rk
        FROM pts p
        CROSS JOIN LATERAL (
          SELECT id, source, target, x1, y1, x2, y2, geom_way
          FROM {EDGES_TABLE}
          ORDER BY geom_way <-> p.pt
          LIMIT {KNN_EDGES}
        ) e
      ),
      endpoints AS (
        SELECT c.idx0, c.source AS node_id, c.x1 AS lon, c.y1 AS lat,
               ST_Distance(ST_SetSRID(ST_MakePoint(c.x1, c.y1), {SRID})::geography,
                           p.pt::geography) AS d
        FROM c JOIN pts p ON p.idx0 = c.idx0
        WHERE c.rk <= {KNN_CANDIDATE_EDGES} AND c.source IS NOT NULL
        UNION ALL
        SELECT c.idx0, c.target AS node_id, c.x2 AS lon, c.y2 AS lat,
               ST_Distance(ST_SetSRID(ST_MakePoint(c.x2, c.y2), {SRID})::geography,
                           p.pt::geography) AS d
        FROM c JOIN pts p ON p.idx0 = c.idx0
        WHERE c.rk <= {KNN_CANDIDATE_EDGES} AND c.target IS NOT NULL
      )
      SELECT idx0, node_id, lon, lat, d
      FROM endpoints
      ORDER BY idx0, d
    """


def nearest_graph_node_ids(db: Session, points: List[LatLng]) -> List[SnappedNode]:
    """Snap batché de tous les points au graphe (1 seule requête).

    Méthode (inchangée depuis l'origine, batchée + directionnelle en v1.2):
      1. KNN PostGIS: les 80 edges les plus proches (opérateur <->, index GiST)
      2. endpoints (source/target) de ces edges, distance géodésique au clic
      3. sélection: parmi les candidats à distance <= 2x le minimum, priorité au
         candidat dans le SENS de voyage (produit scalaire > 0) -> évite les U-turns;
         sinon le plus proche.
    => node_id garanti présent dans le graphe pgrouting (source/target).
    """
    lons = [p.lon for p in points]
    lats = [p.lat for p in points]

    q = text(snap_sql())
    rows = db.execute(q, {"lons": lons, "lats": lats}).all()

    cands: dict[int, list[tuple]] = defaultdict(list)
    for idx0, node_id, lon, lat, d in rows:
        cands[int(idx0)].append((int(node_id), float(lon), float(lat), float(d)))

    out: List[SnappedNode] = []
    for i, pt in enumerate(points):
        lst = cands.get(i)
        if not lst:
            raise ValueError(
                f"No graph node found near point ({pt.lon}, {pt.lat}) "
                f"(empty graph or point far from any road)."
            )
        lst.sort(key=lambda t: t[3])
        min_d = lst[0][3]
        # Candidats "proches": distance <= 2x le minimum (sinon: le plus proche)
        near = [t for t in lst if t[3] <= max(2.0 * min_d, 1.0)]
        dx, dy = _travel_direction(points, i)
        if len(near) > 1 and (dx or dy):
            # Anti U-turn: parmi les candidats proches, on privilégie le PLUS
            # PROCHE candidat situé dans le sens de voyage (produit scalaire > 0).
            fwd = [t for t in near
                   if (t[1] - pt.lon) * dx + (t[2] - pt.lat) * dy > 0]
            pick = fwd[0] if fwd else near[0]
        else:
            pick = near[0]
        out.append(SnappedNode(pick[0], pick[1], pick[2], pick[3]))
    return out


# =====================================================================
# Recherche de chemin: Dijkstra + A* (repli Dijkstra)
# =====================================================================

def dijkstra_sql(source: int, target: int, bbox: Optional[BBox] = None) -> str:
    """SQL pgr_dijkstra (pur — testable sans DB)."""
    edges_sql = edges_sql_excluding_closures(bbox)
    return (
        "SELECT edge\n"
        "FROM pgr_dijkstra(\n"
        f"$$ {edges_sql} $$,\n"
        f"{int(source)},\n{int(target)},\n"
        "directed := true\n)\nWHERE edge > 0"
    )


def astar_sql(
    source: int,
    target: int,
    bbox: Optional[BBox],
    mid_lon: float,
    heur: float,
) -> str:
    """SQL pgr_astar (pur — testable sans DB).

    - bbox != None: coordonnées projetées UTM (zone du centroïde) en mètres.
    - bbox = None: coordonnées degrés (x1..y2 osm2po), heur conservateur.
    """
    inner = edges_sql_excluding_closures(bbox, with_geom=True)
    if bbox is not None:
        zone = utm_zone_srid(mid_lon)
        edges_subquery = f"""
          WITH base AS ({inner}),
               proj AS (SELECT b.*, ST_Transform(b.geom_way, {zone}) AS g_proj FROM base b)
          SELECT id, source, target,
                 ST_X(ST_StartPoint(g_proj)) AS x1, ST_Y(ST_StartPoint(g_proj)) AS y1,
                 ST_X(ST_EndPoint(g_proj))   AS x2, ST_Y(ST_EndPoint(g_proj))   AS y2,
                 cost, reverse_cost
          FROM proj
        """
    else:
        edges_subquery = f"""
          WITH base AS ({inner})
          SELECT id, source, target, x1, y1, x2, y2, cost, reverse_cost
          FROM base
        """
    return (
        "SELECT edge\n"
        "FROM pgr_astar(\n"
        f"$$ {edges_subquery} $$,\n"
        f"{int(source)},\n{int(target)},\n"
        "directed := true,\n"
        f"heur := {float(heur):.10g}\n)\nWHERE edge > 0"
    )


def astar_heur(bbox: Optional[BBox], vcap: float) -> float:
    """Facteur multiplicatif de l'heuristique A*, admissible.

    - coût temps (minutes), coordonnées UTM en mètres:
        time_min = dist_m × 60/(1000 × v_cap)  ->  heur = 0.06/v_cap
      (tout chemin réel met au moins dist/v_cap)
    - coût distance (km): heur = 0.001 (m → km)
    - graphe complet (coordonnées en degrés): 70 km/deg, conservateur
      (admissible en Algérie: 1° de longitude >= 88.5 km aux latitudes DZ)
    """
    time_cost = settings.cost_model == "time"
    if bbox is not None:
        return (0.06 / vcap) if time_cost else 0.001
    return (70.0 * 0.06 / vcap) if time_cost else 70.0


def dijkstra_edges(db: Session, source: int, target: int, bbox: Optional[BBox]) -> List[int]:
    q = text(dijkstra_sql(source, target, bbox))
    rows = db.execute(q).scalars().all()
    return [int(e) for e in rows]


def astar_edges(
    db: Session,
    source: int,
    target: int,
    bbox: Optional[BBox],
    mid_lon: float,
) -> List[int]:
    vcap = get_v_cap(db) or 100.0
    q = text(astar_sql(source, target, bbox, mid_lon, astar_heur(bbox, vcap)))
    rows = db.execute(q).scalars().all()
    return [int(e) for e in rows]


def _choose_algo(d_kin_km: float) -> str:
    # "astar" explicite: toujours A* (repli Dijkstra géré dans route_segment)
    if settings.routing_algo == "astar":
        return "astar"
    # "auto": A* seulement au-delà du seuil de distance à vol d'oiseau
    if settings.routing_algo == "auto" and d_kin_km >= settings.astar_long_route_km:
        return "astar"
    return "dijkstra"


def _bbox_trials(pa: LatLng, pb: LatLng) -> List[Optional[BBox]]:
    return [
        compute_bbox([pa, pb], margin_factor=0.25, min_margin=0.02, max_margin=0.50),
        compute_bbox([pa, pb], margin_factor=0.50, min_margin=0.04, max_margin=1.00),
        compute_bbox([pa, pb], margin_factor=1.00, min_margin=0.08, max_margin=2.00),
        None,  # full graph fallback
    ]


def route_segment(db: Session, a_id: int, b_id: int, pa: LatLng, pb: LatLng) -> Tuple[List[int], str]:
    """Recherche un segment a->b. Retourne (edges, algo) — algo = 'none' si échec."""
    d_kin = haversine_km(pa.lon, pa.lat, pb.lon, pb.lat)
    algo = _choose_algo(d_kin)
    mid_lon = (pa.lon + pb.lon) / 2.0
    trials = _bbox_trials(pa, pb)

    if algo == "astar":
        for i, bbox in enumerate(trials):
            edges = astar_edges(db, a_id, b_id, bbox, mid_lon)
            if edges:
                if i > 0:
                    logger.warning("astar bbox expansion used: trial=%s bbox=%s",
                                   i, "NONE(full)" if bbox is None else bbox)
                return edges, "astar"
        logger.warning("astar failed on all bbox trials (d_kin=%.1f km) -> dijkstra fallback", d_kin)

    for i, bbox in enumerate(trials):
        edges = dijkstra_edges(db, a_id, b_id, bbox)
        if edges:
            if i > 0:
                logger.warning("bbox expansion used: trial=%s bbox=%s",
                               i, "NONE(full)" if bbox is None else bbox)
            return edges, "dijkstra"

    return [], "none"


# =====================================================================
# Cache des segments (invalidation exacte par version d'obstacles)
# =====================================================================

def closure_version_sql() -> str:
    """SQL de la version d'obstacles (pur — testable sans DB)."""
    return """
      SELECT COALESCE(EXTRACT(EPOCH FROM MAX(updated_at)) * 1000000, 0)::bigint
      FROM public.events_road_closed
      WHERE status IN ('validated', 'disabled')
    """


def _closure_version(db: Session) -> int:
    """Version = MAX(updated_at) des events validated/disabled, en µs epoch.

    Le trigger trg_events_updated_at bumpé updated_at à chaque changement
    d'état d'un événement -> invalidation exacte (les drafts n'impactent
    pas le routing et n'invalident donc pas).
    """
    row = db.execute(text(closure_version_sql())).scalar_one()
    return int(row)


def cache_get_sql() -> str:
    """SQL de lecture du cache (pur). Paramètres: :src :dst :v :algo :cm :ttl."""
    return """
      SELECT edges
      FROM public.route_cache
      WHERE src_node = :src AND dst_node = :dst
        AND closure_version = :v
        AND algo = :algo AND cost_model = :cm
        AND created_at > now() - make_interval(mins => :ttl)
      ORDER BY created_at DESC
      LIMIT 1
    """


def cache_put_sql() -> str:
    """SQL d'écriture du cache (pur). Paramètres: :src :dst :v :algo :cm :edges."""
    return """
      INSERT INTO public.route_cache
        (src_node, dst_node, closure_version, algo, cost_model, edges, created_at)
      VALUES (:src, :dst, :v, :algo, :cm, CAST(:edges AS jsonb), now())
      ON CONFLICT (src_node, dst_node, closure_version, algo, cost_model) DO NOTHING
    """


def cache_cleanup_sql() -> str:
    """SQL de nettoyage du cache (pur). Paramètre: :h (heures)."""
    return """
      DELETE FROM public.route_cache
      WHERE created_at < now() - make_interval(hours => :h)
    """


def _cache_get(db: Session, src: int, dst: int, version: int, algo: str) -> Optional[List[int]]:
    if not settings.route_cache:
        return None
    try:
        row = db.execute(text(cache_get_sql()), {
            "src": src, "dst": dst, "v": version,
            "algo": algo, "cm": settings.cost_model,
            "ttl": settings.route_cache_ttl_min,
        }).mappings().first()
        if row is not None:
            return [int(e) for e in row["edges"]]
    except Exception:
        logger.exception("route_cache read failed (ignored)")
    return None


def _cache_put(db: Session, src: int, dst: int, version: int, algo: str, edges: List[int]) -> None:
    if not settings.route_cache or not edges:
        return
    try:
        db.execute(text(cache_put_sql()), {
            "src": src, "dst": dst, "v": version,
            "algo": algo, "cm": settings.cost_model,
            "edges": json.dumps(edges),
        })
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("route_cache write failed (ignored)")


def _cache_cleanup(db: Session) -> None:
    if not settings.route_cache:
        return
    try:
        db.execute(text(cache_cleanup_sql()), {"h": settings.route_cache_retention_hours})
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("route_cache cleanup failed (ignored)")


# =====================================================================
# Synthèse de la route
# =====================================================================

def summarize_sql() -> str:
    """SQL de synthèse distance/durée/GeoJSON (pur). Paramètre: :edge_ids."""
    return f"""
      SELECT
        COALESCE(SUM(e.km), 0)::float8 AS distance_km,
        COALESCE(SUM(CASE WHEN e.kmh > 0 THEN (e.km / e.kmh) * 60 ELSE 0 END), 0)::float8 AS duration_min,
        ST_AsGeoJSON(ST_MakeLine(e.geom_way ORDER BY t.ord)) AS geojson
      FROM unnest(:edge_ids) WITH ORDINALITY AS t(id, ord)
      JOIN {EDGES_TABLE} e ON e.id = t.id
    """


def penalized_count_sql(multi_edge: bool) -> str:
    """SQL du nombre d'edges pénalisés empruntés (pur). Paramètre: :ids."""
    if multi_edge:
        return """
          SELECT COUNT(DISTINCT c.edge_id)::int
          FROM unnest(:ids) AS t(id)
          JOIN public.event_edge_closure c ON c.edge_id = t.id
          WHERE c.status = 'validated' AND c.mode = 'penalty'
            AND now() >= c.start_time AND (c.end_time IS NULL OR now() <= c.end_time)
        """
    return """
      SELECT COUNT(DISTINCT c.edge_id)::int
      FROM unnest(:ids) AS t(id)
      JOIN public.events_road_closed c ON c.edge_id = t.id
      WHERE c.status = 'validated' AND COALESCE(c.mode, 'block') = 'penalty'
        AND now() >= c.start_time AND (c.end_time IS NULL OR now() <= c.end_time)
    """


def summarize_route(db: Session, edge_ids: List[int]) -> Tuple[float, float, Optional[str]]:
    if not edge_ids:
        # 0 distance, empty geometry
        return 0.0, 0.0, None

    # ✅ CORRECTION: Utiliser UNNEST avec ORDINALITY pour garantir l'ordre des segments
    # Sinon `WHERE id = ANY(...)` mélange les segments et ST_LineMerge peut échouer ou faire n'importe quoi.
    q = text(summarize_sql())
    row = db.execute(q, {"edge_ids": edge_ids}).mappings().one()
    return float(row["distance_km"]), float(row["duration_min"]), row["geojson"]


def _count_penalized_used(db: Session, edge_ids: List[int]) -> int:
    """Nombre d'edges empruntés qui étaient en mode 'penalty' (évitement doux)."""
    if not edge_ids:
        return 0
    q = text(penalized_count_sql(settings.multi_edge_closures))
    try:
        return int(db.execute(q, {"ids": edge_ids}).scalar_one() or 0)
    except Exception:
        logger.exception("penalized-edge count failed (ignored)")
        return 0


# =====================================================================
# Orchestration
# =====================================================================

def compute_route(db: Session, req: RouteRequest) -> RouteResponse:
    points: List[LatLng] = [req.start] + (req.vias or []) + [req.end]

    # Snap batché de tous les points au graphe (1 requête)
    snapped = nearest_graph_node_ids(db, points)

    _cache_cleanup(db)
    version = _closure_version(db)

    all_edges: List[int] = []
    algo_counts: dict[str, int] = {}
    cache_hits = 0

    for i in range(len(snapped) - 1):
        a, b = snapped[i], snapped[i + 1]
        if a.node_id == b.node_id:
            # Même noeud de départ et d'arrivée, distance 0, on skip
            continue

        chosen_algo = _choose_algo(haversine_km(a.lon, a.lat, b.lon, b.lat))

        cached = _cache_get(db, a.node_id, b.node_id, version, chosen_algo)
        if cached is not None:
            cache_hits += 1
            algo_counts[chosen_algo] = algo_counts.get(chosen_algo, 0) + 1
            all_edges.extend(cached)
            continue

        seg_edges, algo = route_segment(db, a.node_id, b.node_id, points[i], points[i + 1])
        if not seg_edges:
            # Si on n'a rien trouvé entre 2 points distincts -> échec
            raise ValueError(
                f"No path found between node {a.node_id} and {b.node_id} "
                f"(graph disconnected or closures block the route)."
            )

        _cache_put(db, a.node_id, b.node_id, version, algo, seg_edges)
        algo_counts[algo] = algo_counts.get(algo, 0) + 1
        all_edges.extend(seg_edges)

    distance_km, duration_min, geojson = summarize_route(db, all_edges)
    used_penalized = _count_penalized_used(db, all_edges)

    snapped_out: List[SnappedPoint] = [
        SnappedPoint(lon=s.lon, lat=s.lat, dist_m=round(s.dist_m, 1)) for s in snapped
    ]
    algo_label = "/".join(sorted(algo_counts)) if algo_counts else "none"

    return RouteResponse(
        distance_km=round(distance_km, 3),
        duration_min=round(duration_min, 1),
        edges=all_edges,
        geometry_geojson=geojson,
        snapped=snapped_out,
        algo=algo_label,
        cache_hits=cache_hits,
        used_penalized_edges=used_penalized,
    )

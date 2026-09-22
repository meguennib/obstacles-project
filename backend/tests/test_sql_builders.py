"""Tests unitaires des builders SQL et helpers purs (PAS de base de données)."""
from app.apps.routing.costs import build_cost_expr, time_cost_expr
from app.apps.routing.schemas import LatLng
from app.apps.routing.service import (
    _choose_algo,
    _cost_columns,
    _travel_direction,
    closed_cte,
    compute_bbox,
    haversine_km,
    utm_zone_srid,
)
from app.core.config import settings


# --- Modèle de coût ---

def test_cost_expr_distance_mode_matches_original():
    # Mode "distance" = expressions EXACTES d'origine du projet
    assert build_cost_expr("cost", "e", "distance") == \
        "COALESCE(e.dynamic_cost, e.cost)"
    assert build_cost_expr("reverse_cost", "e", "distance") == \
        "COALESCE(e.dynamic_reverse_cost, e.reverse_cost, e.dynamic_cost, e.cost)"


def test_cost_expr_time_mode():
    c = build_cost_expr("cost", "e", "time")
    assert "e.kmh" in c and "dynamic_cost" in c and "60.0" in c
    r = build_cost_expr("reverse_cost", "e", "time")
    assert "dynamic_reverse_cost" in r and "dynamic_cost" in r
    # override manuel prioritaire
    assert c.startswith("COALESCE(e.dynamic_cost,")


def test_time_cost_expr_fallback_distance():
    e = time_cost_expr("e")
    assert e == "CASE WHEN e.kmh > 0 THEN e.km / e.kmh * 60.0 ELSE e.km END"


# --- CTE obstacles ---

def test_closed_cte_multi_edge():
    backup = settings.multi_edge_closures
    try:
        settings.multi_edge_closures = True
        s = closed_cte()
        assert "event_edge_closure" in s
        assert "status = 'validated'" in s
        assert "end_time IS NULL OR now() <= end_time" in s
    finally:
        settings.multi_edge_closures = backup


def test_closed_cte_legacy():
    backup = settings.multi_edge_closures
    try:
        settings.multi_edge_closures = False
        s = closed_cte()
        assert "events_road_closed" in s
        assert "edge_id IS NOT NULL" in s
        assert "end_time IS NULL OR now() <= end_time" in s
    finally:
        settings.multi_edge_closures = backup


def test_cost_columns_block_and_penalty():
    cost_sql, rev_sql = _cost_columns("e")
    # blocage par sens
    assert "c.direction IN ('both', 'forward') THEN -1" in cost_sql
    assert "c.direction IN ('both', 'reverse') THEN -1" in rev_sql
    # pénalité
    assert "penalty_factor" in cost_sql and "penalty_factor" in rev_sql
    # sans obstacle -> coût de base
    assert cost_sql.rstrip().endswith("END AS cost")
    assert rev_sql.rstrip().endswith("END AS reverse_cost")


# --- UTM / heuristique A* ---

def test_utm_zones_algeria():
    assert utm_zone_srid(-8.67) == 32629   # ouest (Tindouf)
    assert utm_zone_srid(-0.62) == 32630   # Oran
    assert utm_zone_srid(0.0) == 32631
    assert utm_zone_srid(3.05) == 32631    # Alger
    assert utm_zone_srid(6.6) == 32632     # Constantine
    assert utm_zone_srid(11.98) == 32632   # est


def test_haversine():
    # 1° de latitude ~= 111.19 km (R = 6371.0088)
    assert abs(haversine_km(0, 0, 0, 1) - 111.195) < 0.05
    # 0.008° de longitude à latitude 35.66° ~= 0.725 km (cellule du grid)
    assert abs(haversine_km(-0.640, 35.66, -0.632, 35.66) - 0.725) < 0.01


# --- BBox ---

def test_compute_bbox_margins_and_clamp():
    pts = [LatLng(lon=3.0, lat=36.0), LatLng(lon=3.4, lat=36.0)]
    b = compute_bbox(pts, margin_factor=0.25, min_margin=0.02, max_margin=0.50)
    assert b.min_lon < 3.0 and b.max_lon > 3.4
    assert b.min_lat < 36.0 and b.max_lat > 36.0

    # margin plafonné par max_margin
    pts2 = [LatLng(lon=-10.0, lat=30.0), LatLng(lon=10.0, lat=30.0)]
    b2 = compute_bbox(pts2, margin_factor=0.25, min_margin=0.02, max_margin=0.50)
    assert (b2.max_lon - b2.min_lon) <= 20.0 + 2 * 0.50 + 1e-9

    # clamp sur les bornes du monde
    b3 = compute_bbox(
        [LatLng(lon=-180.0, lat=0.0), LatLng(lon=-179.0, lat=0.0)],
        margin_factor=0.25, min_margin=0.02, max_margin=0.50,
    )
    assert b3.min_lon >= -180.0 and b3.max_lon <= 180.0


# --- Snap directionnel ---

def test_travel_direction():
    pts = [LatLng(lon=0.0, lat=0.0), LatLng(lon=1.0, lat=0.0), LatLng(lon=2.0, lat=1.0)]
    dx, dy = _travel_direction(pts, 0)   # départ: vers le prochain point
    assert dx > 0 and dy == 0
    dx, dy = _travel_direction(pts, 1)   # milieu: avant-arrière
    assert dx > 0 and dy > 0
    dx, dy = _travel_direction(pts, 2)   # arrivée: sens d'arrivée
    assert dx > 0 and dy > 0
    dx, dy = _travel_direction([pts[0]], 0)
    assert dx == 0 and dy == 0


# --- Dispatch algorithme ---

def test_choose_algo():
    backup = (settings.routing_algo, settings.astar_long_route_km)
    try:
        settings.routing_algo = "auto"
        settings.astar_long_route_km = 40.0
        assert _choose_algo(10.0) == "dijkstra"
        assert _choose_algo(50.0) == "astar"
        settings.routing_algo = "dijkstra"
        assert _choose_algo(500.0) == "dijkstra"
        settings.routing_algo = "astar"
        assert _choose_algo(1.0) == "astar"
    finally:
        settings.routing_algo, settings.astar_long_route_km = backup

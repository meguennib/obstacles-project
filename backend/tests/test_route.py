"""Tests d'intégration routing — durcis (plus de tolérance 404).

Le fixture `graph` (conftest) skippe si le graphe est vide; sinon 200 est exigé.
"""
import pytest

from tests.grid import node

# Points réels Algérie (utilisés si le graphe est un import OSM complet)
ALGER_START = {"lon": 3.04197, "lat": 36.7525}
ALGER_END = {"lon": 3.09, "lat": 36.73}
ALGER_VIA = {"lon": 3.06, "lat": 36.745}

# Graphe synthétique (grid) : coins de la grille 12x12
GRID_START = node(0, 0)
GRID_END = node(11, 11)
GRID_VIA = node(5, 5)


def _points(graph):
    if graph["is_grid"]:
        return GRID_START, GRID_END, GRID_VIA
    return ALGER_START, ALGER_END, ALGER_VIA


@pytest.mark.integration
def test_route_no_via(client, graph):
    s, e, _ = _points(graph)
    r = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["distance_km"] > 0
    assert len(d["edges"]) > 0
    assert d["geometry_geojson"]
    assert d["algo"] in ("dijkstra", "astar", "astar/dijkstra")
    assert len(d["snapped"]) == 2
    assert r.headers.get("X-Route-Cache") in ("hit", "miss", "disabled")
    assert r.headers.get("X-Route-Algo") in ("dijkstra", "astar")


@pytest.mark.integration
def test_route_with_via(client, graph):
    s, e, v = _points(graph)
    r = client.post("/api/v1/route", json={"start": s, "end": e, "vias": [v]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["distance_km"] > 0
    assert len(d["edges"]) > 0
    assert len(d["snapped"]) == 3


@pytest.mark.integration
def test_route_same_point(client, graph):
    # Départ = arrivée -> distance 0, pas d'erreur
    s, _, _ = _points(graph)
    r = client.post("/api/v1/route", json={"start": s, "end": s, "vias": []})
    assert r.status_code == 200, r.text
    assert r.json()["distance_km"] == 0.0

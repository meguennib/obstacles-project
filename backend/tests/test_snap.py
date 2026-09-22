"""Tests d'intégration du snap au graphe (v1.2: batché + directionnel)."""
import pytest

from tests.grid import node, node_lat, node_lon


@pytest.mark.integration
def test_snap_exact_node(client, grid_only):
    # Point EXACTEMENT sur un nœud du grid -> offset quasi nul
    s, e = node(5, 5), node(5, 6)
    r = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
    assert r.status_code == 200, r.text
    snapped = r.json()["snapped"]
    assert snapped[0]["dist_m"] < 1.0
    assert snapped[0]["lon"] == pytest.approx(node_lon(5), abs=1e-9)
    assert snapped[0]["lat"] == pytest.approx(node_lat(5), abs=1e-9)


@pytest.mark.integration
def test_snap_directional_anti_uturn(client, grid_only):
    # Point au MILIEU de l'edge horizontal (0,0)-(0,1), trajet vers l'EST:
    # le snap doit choisir l'endpoint AVANT (0,1) et non l'endpoint arrière (0,0).
    mid = {"lon": (node_lon(0) + node_lon(1)) / 2, "lat": node_lat(0)}
    r = client.post("/api/v1/route", json={"start": mid, "end": node(0, 11), "vias": []})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["snapped"][0]["lon"] == pytest.approx(node_lon(1), abs=1e-9)
    # Suite du trajet: les 10 edges horizontaux de la ligne 0 (highway)
    assert len(d["edges"]) == 10

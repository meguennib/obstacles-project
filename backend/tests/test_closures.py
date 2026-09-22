"""Tests d'intégration du modèle d'obstacles (v1.2) — déterministes sur le grid.

Sémantiques vérifiées:
  - détour déterministe après fermeture (et restauration après disable)
  - fermeture multi-edges dérivée de la géométrie (firewall = 400)
  - rejet d'overlap (409)
  - fermeture sans date de fin (end_time null)
  - sens de la fermeture (forward bloque un seul sens)
  - pénalité (mode=penalty): l'edge reste empruntable, comptabilisé
"""
import pytest

from tests.grid import h_edge, node, node_lat, node_lon, v_edge
from tests.helpers import create_event, disable_event, edge_wkt, make_closure

GRID_START = node(0, 0)
GRID_END = node(11, 11)


def _row2_line_wkt() -> str:
    return f"LINESTRING({node_lon(0)} {node_lat(2)}, {node_lon(11)} {node_lat(2)})"


@pytest.mark.integration
def test_detour_after_closure(client, grid_only):
    r1 = client.post("/api/v1/route", json={"start": GRID_START, "end": GRID_END, "vias": []})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()

    first_edge = d1["edges"][0]
    ev = make_closure(client, first_edge, edge_wkt(first_edge), reason="detour test")
    try:
        r2 = client.post("/api/v1/route", json={"start": GRID_START, "end": GRID_END, "vias": []})
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        # détour effectif: l'edge fermé n'est plus emprunté (distance équivalente
        # possible sur le grid: les deux "L" highway sont de même longueur)
        assert first_edge not in d2["edges"]
        assert d2["edges"] != d1["edges"]
        assert d2["distance_km"] >= d1["distance_km"]
        assert d2["cache_hits"] == 0  # cache invalidé par la nouvelle version
    finally:
        disable_event(client, ev["id"])

    # restauration exacte du tracé d'origine
    r3 = client.post("/api/v1/route", json={"start": GRID_START, "end": GRID_END, "vias": []})
    assert r3.status_code == 200, r3.text
    assert r3.json()["edges"] == d1["edges"]


@pytest.mark.integration
def test_multi_edge_derive_from_line(client, grid_only):
    # Route directe traversant la ligne 2 (avant fermeture)
    s, e = node(1, 3), node(3, 3)
    r1 = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert len(d1["edges"]) == 2  # chemin direct: 2 edges verticaux

    # Ligne traversant TOUTE la ligne 2 -> dérive ~35 edges (11 horizontaux
    # + 12 verticaux entrants + 12 verticaux sortants)
    ev = make_closure(client, h_edge(2, 0), _row2_line_wkt(),
                      reason="multi-edge firewall", derive_from_geom=True)
    try:
        assert ev["affected_edges"] >= 11
        # La ligne 2 devient un firewall: coupure complète du grid
        r2 = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
        assert r2.status_code == 400
        assert "No path" in r2.json()["detail"]
    finally:
        disable_event(client, ev["id"])

    # restauration
    r3 = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
    assert r3.status_code == 200, r3.text
    assert r3.json()["edges"] == d1["edges"]


@pytest.mark.integration
def test_overlap_rejected(client, grid_only):
    eid = h_edge(4, 0)
    wkt = edge_wkt(eid)

    ev_a = make_closure(client, eid, wkt, reason="A")
    ev_b = create_event(client, eid, wkt, reason="B")
    r = client.post(f"/api/v1/events/road_closed/{ev_b['id']}/validate")
    assert r.status_code == 409
    assert "overlap" in r.json()["detail"].lower()

    disable_event(client, ev_a["id"])
    # Une fois A désactivée, B peut être validée (contrainte sur validated only)
    r2 = client.post(f"/api/v1/events/road_closed/{ev_b['id']}/validate")
    assert r2.status_code == 200, r2.text
    disable_event(client, ev_b["id"])


@pytest.mark.integration
def test_open_end_time(client, grid_only):
    eid = h_edge(6, 0)
    ev = make_closure(client, eid, edge_wkt(eid), reason="open end", end=None)
    assert ev["end_time"] is None

    r = client.get("/api/v1/events/road_closed",
                   params={"status": "validated", "active_now": "true"})
    assert r.status_code == 200
    assert any(it["id"] == ev["id"] and it["end_time"] is None for it in r.json())

    disable_event(client, ev["id"])
    r2 = client.get("/api/v1/events/road_closed",
                    params={"status": "validated", "active_now": "true"})
    assert all(it["id"] != ev["id"] for it in r2.json())


@pytest.mark.integration
def test_direction_forward_only(client, grid_only):
    # e1  = (0,0)->(0,1) fermé EN FORWARD (sens direct uniquement)
    # e2  = (0,1)->(0,2) fermé EN BOTH
    # v00 = (0,0)->(1,0) fermé EN BOTH (force l'arrivée via e1 en contresens)
    # => si "forward" était mal implémenté comme "both", la route serait impossible
    e1, e2, v00 = h_edge(0, 0), h_edge(0, 1), v_edge(0, 0)
    s, e = node(0, 2), node(0, 0)   # trajet ouest

    r1 = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert set(d1["edges"]) == {e1, e2}  # chemin direct en contresens

    ev1 = make_closure(client, e1, edge_wkt(e1), reason="forward", direction="forward")
    ev2 = make_closure(client, e2, edge_wkt(e2), reason="both", direction="both")
    ev3 = make_closure(client, v00, edge_wkt(v00), reason="both-v", direction="both")
    try:
        r2 = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        # e2 (both) est contourné; e1 reste empruntable EN CONTRESENS.
        # Tracé unique (vérifié par simulation exacte du graphe):
        # (0,2) -> (1,2) -> (1,1) -> (0,1) -> (0,0)
        expected = [v_edge(0, 2), h_edge(1, 1), v_edge(0, 1), e1]
        assert d2["edges"] == expected
    finally:
        disable_event(client, ev1["id"])
        disable_event(client, ev2["id"])
        disable_event(client, ev3["id"])


@pytest.mark.integration
def test_penalty_mode(client, grid_only):
    # Pénalité x100 sur la ligne 2 (multi-edges): le "mur" reste PÉNÉTRABLE.
    # Toute traversée du grid impose exactement 2 edges pénalisés (entrée +
    # sortie de la bande ligne 2); l'optimiseur les choisit AU PLUS CHEAP:
    # traversée en colonne 0 (highway kmh=100), avec détour ligne 0 ouest +
    # colonne 0 + ligne 11 est — vérifié par simulation exacte du graphe.
    s, e = node(0, 5), node(11, 5)
    r1 = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    # sans pénalité: colonne 5 droite (11 edges verticaux, 9.797 km)
    assert d1["edges"] == [v_edge(r, 5) for r in range(11)]
    assert d1["distance_km"] == 9.797
    assert d1["used_penalized_edges"] == 0

    ev = make_closure(client, h_edge(2, 0), _row2_line_wkt(),
                      reason="penalty", derive_from_geom=True,
                      mode="penalty", penalty_factor=100.0)
    try:
        r2 = client.post("/api/v1/route", json={"start": s, "end": e, "vias": []})
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        expected = (
            [h_edge(0, c) for c in range(4, -1, -1)]   # ligne 0 vers l'ouest
            + [v_edge(r, 0) for r in range(11)]        # colonne 0 (highway)
            + [h_edge(11, c) for c in range(0, 5)]     # ligne 11 vers l'est
        )
        assert d2["edges"] == expected
        assert d2["distance_km"] == 17.051
        assert d2["used_penalized_edges"] == 2
    finally:
        disable_event(client, ev["id"])

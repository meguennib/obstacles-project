"""Tests d'intégration du cache de segments (v1.2)."""
import pytest

from tests.grid import h_edge, node
from tests.helpers import disable_event, edge_wkt, make_closure

GRID_START = node(0, 0)
GRID_END = node(11, 11)


@pytest.mark.integration
def test_cache_hit_and_invalidation(client, grid_only):
    # Fermeture "neutre" (edge hors du tracé optimal) juste pour forcer une
    # NOUVELLE version d'obstacles unique -> la suite est déterministe.
    ev = make_closure(client, h_edge(6, 6), edge_wkt(h_edge(6, 6)), reason="cache bump")
    try:
        r1 = client.post("/api/v1/route", json={"start": GRID_START, "end": GRID_END, "vias": []})
        assert r1.status_code == 200, r1.text
        assert r1.json()["cache_hits"] == 0  # 1ère requête à cette version: miss

        r2 = client.post("/api/v1/route", json={"start": GRID_START, "end": GRID_END, "vias": []})
        assert r2.status_code == 200, r2.text
        assert r2.json()["cache_hits"] == 1  # segment servi par le cache
        assert r2.json()["edges"] == r1.json()["edges"]
    finally:
        disable_event(client, ev["id"])  # bump de version -> invalidation

    r3 = client.post("/api/v1/route", json={"start": GRID_START, "end": GRID_END, "vias": []})
    assert r3.status_code == 200, r3.text
    assert r3.json()["cache_hits"] == 0  # nouvelle version: pas de hit

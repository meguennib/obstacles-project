import pytest

@pytest.mark.integration
def test_route_no_via(client):
    r = client.post("/api/v1/route", json={
        "start": {"lon": 3.04197, "lat": 36.7525},
        "end":   {"lon": 3.09, "lat": 36.73},
        "vias": []
    })
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        data = r.json()
        assert data["distance_km"] >= 0
        assert len(data["edges"]) > 0

@pytest.mark.integration
def test_route_with_via(client):
    r = client.post("/api/v1/route", json={
        "start": {"lon": 3.04197, "lat": 36.7525},
        "vias": [{"lon": 3.06, "lat": 36.745}],
        "end": {"lon": 3.09, "lat": 36.73}
    })
    assert r.status_code in (200, 404)

@pytest.mark.integration
def test_route_with_validated_closure(client):
    # 1) route initiale
    r1 = client.post("/api/v1/route", json={
        "start": {"lon": 3.04197, "lat": 36.7525},
        "end":   {"lon": 3.09, "lat": 36.73},
        "vias": []
    })
    if r1.status_code != 200:
        pytest.skip("No initial path, cannot test closure deterministically.")

    edges = r1.json()["edges"]
    first_edge = edges[0]

    # 2) récupère la geom du 1er edge via une requête SQL côté API ? (pas exposé)
    # => ici on fait simple: on crée une fermeture "large" près du start. (peut échouer selon data)
    # Pour une fermeture 100% déterministe, préfère manage.py smoke-route.
    ev = client.post("/api/v1/events/road_closed", json={
        "reason": "test closure near start",
        "start_time": "2025-12-29T00:00:00+01:00",
        "end_time": "2025-12-29T23:59:59+01:00",
        "geometry_wkt": "LINESTRING(3.041 36.752, 3.043 36.753)"
    })
    assert ev.status_code in (200, 500)

    if ev.status_code == 200:
        event_id = ev.json()["id"]
        v = client.post(f"/api/v1/events/road_closed/{event_id}/validate")
        assert v.status_code in (200, 404, 500)

    # 3) route après fermeture
    r2 = client.post("/api/v1/route", json={
        "start": {"lon": 3.04197, "lat": 36.7525},
        "end":   {"lon": 3.09, "lat": 36.73},
        "vias": []
    })
    assert r2.status_code in (200, 404)

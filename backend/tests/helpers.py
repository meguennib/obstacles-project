"""Helpers de tests d'intégration (client API + SQL direct)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.db import SessionLocal


def edge_wkt(edge_id: int) -> str:
    with SessionLocal() as db:
        return db.execute(
            text("SELECT ST_AsText(ST_LineMerge(geom_way)) FROM public.algeria_2po_4pgr WHERE id = :id"),
            {"id": edge_id},
        ).scalar_one()


def create_event(client, edge_id, geom_wkt, reason="test", start=None, end=None, **kw) -> dict:
    """Crée un événement draft. end=None -> fermeture sans date de fin."""
    now = datetime.now(timezone.utc)
    start = start or (now - timedelta(minutes=5))
    payload = {
        "reason": reason,
        "start_time": start.isoformat(),
        "end_time": end.isoformat() if end else None,
        "geometry_wkt": geom_wkt,
        "edge_id": edge_id,
    }
    payload.update(kw)
    r = client.post("/api/v1/events/road_closed", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def make_closure(client, edge_id, geom_wkt, reason="test", end=None, **kw) -> dict:
    """Crée + valide une fermeture active maintenant."""
    ev = create_event(client, edge_id, geom_wkt, reason=reason, end=end, **kw)
    r = client.post(f"/api/v1/events/road_closed/{ev['id']}/validate")
    assert r.status_code == 200, r.text
    return r.json()


def disable_event(client, event_id: int):
    r = client.post(f"/api/v1/events/road_closed/{event_id}/disable")
    assert r.status_code == 200, r.text
    return r.json()

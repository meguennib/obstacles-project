from sqlalchemy import text
from sqlalchemy.orm import Session
from app.apps.events.schemas import RoadClosedCreate
from sqlalchemy.exc import IntegrityError

def create_road_closed(db: Session, payload: RoadClosedCreate) -> dict:
    q = text("""
      INSERT INTO public.events_road_closed(status, reason, start_time, end_time, geom, edge_id)
      VALUES (
        'draft',
        :reason,
        :start_time,
        :end_time,
        ST_SetSRID(ST_GeomFromText(:wkt), 4326),
        :edge_id
      )
      RETURNING id, status, start_time, end_time, reason, edge_id
    """)
    row = db.execute(q, {
        "reason": payload.reason,
        "start_time": payload.start_time,
        "end_time": payload.end_time,
        "wkt": payload.geometry_wkt,
        "edge_id": payload.edge_id
    }).mappings().one()
    db.commit()
    return dict(row)


def validate_road_closed(db: Session, event_id: int) -> dict:
    row = db.execute(text("""
      SELECT id, edge_id
      FROM public.events_road_closed
      WHERE id = :id
    """), {"id": event_id}).mappings().one_or_none()

    if row is None:
        raise ValueError("Event not found")
    if row["edge_id"] is None:
        raise ValueError("Cannot validate: edge_id is required")

    q = text("""
      UPDATE public.events_road_closed
      SET status='validated'
      WHERE id=:id
      RETURNING id, status, start_time, end_time, reason, edge_id
    """)
    out = db.execute(q, {"id": event_id}).mappings().one()

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError("Cannot validate: overlap with another validated event on same edge_id/time window")

    return dict(out)

def list_road_closed(
    db: Session,
    status: str | None,
    active_now: bool | None,
    edge_id: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    where = []
    params: dict = {"limit": limit, "offset": offset}

    if status:
        where.append("c.status = :status")
        params["status"] = status

    if edge_id is not None:
        where.append("c.edge_id = :edge_id")
        params["edge_id"] = edge_id

    if active_now is True:
        where.append("now() BETWEEN c.start_time AND c.end_time")
    elif active_now is False:
        where.append("NOT (now() BETWEEN c.start_time AND c.end_time)")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    q = text(f"""
      SELECT c.id, c.status, c.start_time, c.end_time, c.reason, c.edge_id
      FROM public.events_road_closed c
      {where_sql}
      ORDER BY c.id DESC
      LIMIT :limit OFFSET :offset
    """)
    rows = db.execute(q, params).mappings().all()
    return [dict(r) for r in rows]


def get_road_closed(db: Session, event_id: int) -> dict | None:
    q = text("""
      SELECT
        c.id, c.status, c.start_time, c.end_time, c.reason, c.edge_id,
        ST_AsText(c.geom) AS geometry_wkt
      FROM public.events_road_closed c
      WHERE c.id = :id
    """)
    row = db.execute(q, {"id": event_id}).mappings().one_or_none()
    return dict(row) if row else None

def disable_road_closed(db: Session, event_id: int) -> dict:
    # désactive (soft delete)
    q = text("""
      UPDATE public.events_road_closed
      SET status='disabled'
      WHERE id=:id
      RETURNING id, status, start_time, end_time, reason, edge_id
    """)
    row = db.execute(q, {"id": event_id}).mappings().one_or_none()
    if not row:
        raise ValueError("Event not found")
    db.commit()
    return dict(row)

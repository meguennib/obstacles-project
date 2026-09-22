import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.apps.routing.constants import EDGES_TABLE

logger = logging.getLogger("events")

# Plafond de sécurité: une ligne tracée ne doit pas exclure tout un pays.
MAX_DERIVED_EDGES = 500


def _returning_cols() -> str:
    return (
        "id, status, start_time, end_time, reason, edge_id, "
        "derive_from_geom, direction, mode, penalty_factor"
    )


def create_road_closed(db: Session, payload) -> dict:
    q = text(f"""
      INSERT INTO public.events_road_closed(
        status, reason, start_time, end_time, geom, edge_id,
        derive_from_geom, direction, mode, penalty_factor
      )
      VALUES (
        'draft',
        :reason,
        :start_time,
        :end_time,
        ST_SetSRID(ST_GeomFromText(:wkt), 4326),
        :edge_id,
        :derive_from_geom,
        :direction,
        :mode,
        :penalty_factor
      )
      RETURNING {_returning_cols()}
    """)
    row = db.execute(q, {
        "reason": payload.reason,
        "start_time": payload.start_time,
        "end_time": payload.end_time,
        "wkt": payload.geometry_wkt,
        "edge_id": payload.edge_id,
        "derive_from_geom": payload.derive_from_geom,
        "direction": payload.direction,
        "mode": payload.mode,
        "penalty_factor": payload.penalty_factor,
    }).mappings().one()
    db.commit()
    out = dict(row)
    out["affected_edges"] = 0
    return out


# Tolérance de dérive: une ligne tracée au clic diffère de quelques mètres
# (voire moins d'un ulp au niveau des nœuds) de la route réelle -> on teste
# l'intersection CONTRE LE BUFFER, pas contre la ligne brute. Sinon un edge
# dont l'extrémité "s'arrête un cheveu avant" la ligne serait manqué.
DERIVE_BUFFER_DEG = 0.002  # ~130-220 m selon la latitude


def _intersect_edges_sql() -> str:
    """Fragment SQL: edges traversés/frôlés par la géométrie :wkt (bufferée)."""
    buffered = f"ST_SetSRID(ST_Buffer(ST_GeomFromText(:wkt), {DERIVE_BUFFER_DEG}), 4326)"
    return (
        f"FROM {EDGES_TABLE} e\n"
        f"WHERE e.geom_way && {buffered}\n"
        f"  AND ST_Intersects(ST_LineMerge(e.geom_way), {buffered})"
    )


def _derive_edges(db: Session, event_id: int, row, wkt: str) -> int:
    """v1.2: peuple event_edge_closure avec tous les edges intersectés par la ligne.

    Retourne le nombre d'edges concernés (>= 1, l'edge anchor inclus).
    """
    count = db.execute(text(
        f"SELECT COUNT(*)::int {_intersect_edges_sql()}"
    ), {"wkt": wkt}).scalar_one()
    if count > MAX_DERIVED_EDGES:
        raise ValueError(
            f"Cannot validate: geometry intersects {count} edges "
            f"(max {MAX_DERIVED_EDGES}). Shorten the line or narrow the closure."
        )

    db.execute(text(f"""
      INSERT INTO public.event_edge_closure
        (event_id, edge_id, start_time, end_time, status, direction, mode, penalty_factor)
      SELECT :id, e.id, :start_time, :end_time, 'validated', :direction, :mode, :penalty_factor
      {_intersect_edges_sql()}
      ON CONFLICT (event_id, edge_id) DO NOTHING
    """), {
        "id": event_id,
        "wkt": wkt,
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "direction": row["direction"],
        "mode": row["mode"],
        "penalty_factor": row["penalty_factor"],
    })
    affected = db.execute(text(
        "SELECT COUNT(*)::int FROM public.event_edge_closure WHERE event_id = :id"
    ), {"id": event_id}).scalar_one()
    return int(affected)


def validate_road_closed(db: Session, event_id: int) -> dict:
    row = db.execute(text("""
      SELECT id, edge_id, start_time, end_time,
             COALESCE(derive_from_geom, false) AS derive_from_geom,
             COALESCE(direction, 'both') AS direction,
             COALESCE(mode, 'block') AS mode,
             COALESCE(penalty_factor, 5) AS penalty_factor,
             ST_AsText(geom) AS geom_wkt
      FROM public.events_road_closed
      WHERE id = :id
    """), {"id": event_id}).mappings().one_or_none()

    if row is None:
        raise ValueError("Event not found")
    if row["edge_id"] is None:
        raise ValueError("Cannot validate: edge_id is required")

    try:
        # v1.2: liage événement -> edges (multi-edges si derive_from_geom + LineString)
        geom_wkt = row["geom_wkt"]
        if row["derive_from_geom"] and geom_wkt and geom_wkt.upper().startswith("LINESTRING"):
            affected = _derive_edges(db, event_id, row, geom_wkt)
        else:
            db.execute(text("""
              INSERT INTO public.event_edge_closure
                (event_id, edge_id, start_time, end_time, status, direction, mode, penalty_factor)
              VALUES (:id, :edge_id, :start_time, :end_time, 'validated',
                      :direction, :mode, :penalty_factor)
              ON CONFLICT (event_id, edge_id) DO NOTHING
            """), {
                "id": event_id,
                "edge_id": row["edge_id"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "direction": row["direction"],
                "mode": row["mode"],
                "penalty_factor": row["penalty_factor"],
            })
            affected = 1

        out = db.execute(text(f"""
          UPDATE public.events_road_closed
          SET status='validated'
          WHERE id=:id
          RETURNING {_returning_cols()}
        """), {"id": event_id}).mappings().one()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError(
            "Cannot validate: overlap with another validated event on same edge_id/time window"
        )

    result = dict(out)
    result["affected_edges"] = int(affected)
    return result


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

    # v1.2: end_time NULL = "jusqu'à nouvel ordre" (toujours actif)
    active_expr = "now() >= c.start_time AND (c.end_time IS NULL OR now() <= c.end_time)"
    if active_now is True:
        where.append(active_expr)
    elif active_now is False:
        where.append(f"NOT ({active_expr})")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    q = text(f"""
      SELECT c.*,
             (SELECT COUNT(*)::int FROM public.event_edge_closure x
               WHERE x.event_id = c.id) AS affected_edges
      FROM public.events_road_closed c
      {where_sql}
      ORDER BY c.id DESC
      LIMIT :limit OFFSET :offset
    """)
    rows = db.execute(q, params).mappings().all()
    return [dict(r) for r in rows]


def get_road_closed(db: Session, event_id: int) -> dict | None:
    q = text(f"""
      SELECT c.*,
             ST_AsText(c.geom) AS geometry_wkt,
             (SELECT COALESCE(jsonb_agg(x.edge_id ORDER BY x.edge_id), '[]'::jsonb)
              FROM public.event_edge_closure x
              WHERE x.event_id = c.id) AS derived_edges,
             (SELECT COUNT(*)::int FROM public.event_edge_closure x
               WHERE x.event_id = c.id) AS affected_edges
      FROM public.events_road_closed c
      WHERE c.id = :id
    """)
    row = db.execute(q, {"id": event_id}).mappings().one_or_none()
    if row is None:
        return None
    out = dict(row)
    if isinstance(out.get("derived_edges"), str):
        out["derived_edges"] = json.loads(out["derived_edges"])
    return out


def disable_road_closed(db: Session, event_id: int) -> dict:
    # désactive (soft delete)
    exists = db.execute(text(
        "SELECT id FROM public.events_road_closed WHERE id = :id"
    ), {"id": event_id}).scalar_one_or_none()
    if exists is None:
        raise ValueError("Event not found")

    # v1.2: cascade sur le liage edges
    db.execute(text(
        "UPDATE public.event_edge_closure SET status='disabled' WHERE event_id = :id"
    ), {"id": event_id})

    q = text(f"""
      UPDATE public.events_road_closed
      SET status='disabled'
      WHERE id=:id
      RETURNING {_returning_cols()}
    """)
    out = db.execute(q, {"id": event_id}).mappings().one()
    db.commit()
    result = dict(out)
    result["affected_edges"] = 0
    return result

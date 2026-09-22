from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("stats")


def _active_closures_count(db: Session) -> int:
    # v1.2: end_time NULL = "jusqu'à nouvel ordre" (actif)
    q = text("""
      SELECT COUNT(*)::int AS c
      FROM public.events_road_closed
      WHERE status = 'validated'
        AND edge_id IS NOT NULL
        AND now() >= start_time
        AND (end_time IS NULL OR now() <= end_time)
    """)
    r = db.execute(q).mappings().first()
    return int(r["c"] or 0)


def record_route_success(
    db: Session,
    start_lon: float | None,
    start_lat: float | None,
    end_lon: float | None,
    end_lat: float | None,
    vias_json,
    profile: str,
    distance_km: float,
    duration_min: float,
    edges: list[int],
    google_distance_km: float | None = None,
    google_duration_min: float | None = None,
    used_penalized_edges: int = 0,
) -> None:
    try:
        c = _active_closures_count(db)
        had = c > 0

        delta_distance = None
        delta_duration = None
        if google_distance_km is not None:
            delta_distance = float(distance_km) - float(google_distance_km)
        if google_duration_min is not None:
            delta_duration = float(duration_min) - float(google_duration_min)

        ins = text("""
          INSERT INTO public.stats_route_log(
            start_lon, start_lat, end_lon, end_lat,
            vias, profile,
            distance_km, duration_min,
            edge_count, edges,
            had_active_closures, active_closure_count,
            google_distance_km, google_duration_min,
            delta_distance_km, delta_duration_min,
            used_penalized_edges
          )
          VALUES (
            :start_lon, :start_lat, :end_lon, :end_lat,
            CAST(:vias AS jsonb), :profile,
            :distance_km, :duration_min,
            :edge_count, CAST(:edges AS jsonb),
            :had, :c,
            :gdist, :gdur,
            :ddist, :ddur,
            :used_pen
          )
        """)
        db.execute(ins, {
            "start_lon": start_lon,
            "start_lat": start_lat,
            "end_lon": end_lon,
            "end_lat": end_lat,
            "vias": json.dumps(vias_json or []),
            "profile": profile,
            "distance_km": distance_km,
            "duration_min": duration_min,
            "edge_count": len(edges),
            "edges": json.dumps(edges or []),
            "had": had,
            "c": c,
            "gdist": google_distance_km,
            "gdur": google_duration_min,
            "ddist": delta_distance,
            "ddur": delta_duration,
            "used_pen": used_penalized_edges,
        })

        # v1.2: agrégation edges/jour en UNE seule requête (fin de l'executemany),
        # déduplication des edges répétés (segments qui se recoupent).
        if edges:
            up = text("""
              INSERT INTO public.stats_edge_usage_daily(day, edge_id, hits, last_seen)
              SELECT :day, t.id, 1, now()
              FROM unnest(CAST(:ids AS int[])) AS t(id)
              GROUP BY t.id
              ON CONFLICT (day, edge_id) DO UPDATE
              SET hits = public.stats_edge_usage_daily.hits + 1,
                  last_seen = EXCLUDED.last_seen
            """)
            db.execute(up, {"day": date.today(), "ids": [int(e) for e in edges]})

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("record_route_success failed (routing itself succeeded)")


def record_route_failure(
    db: Session,
    start_lon: float | None,
    start_lat: float | None,
    end_lon: float | None,
    end_lat: float | None,
    vias_json,
    profile: str,
    error_type: str,
    error_message: str,
) -> None:
    try:
        ins = text("""
          INSERT INTO public.stats_route_fail_log(
            start_lon, start_lat, end_lon, end_lat,
            vias, profile,
            error_type, error_message
          )
          VALUES (
            :start_lon, :start_lat, :end_lon, :end_lat,
            CAST(:vias AS jsonb), :profile,
            :error_type, :error_message
          )
        """)
        db.execute(ins, {
            "start_lon": start_lon,
            "start_lat": start_lat,
            "end_lon": end_lon,
            "end_lat": end_lat,
            "vias": json.dumps(vias_json or []),
            "profile": profile,
            "error_type": error_type,
            "error_message": error_message[:1000],
        })
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("record_route_failure failed")

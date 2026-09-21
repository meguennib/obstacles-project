from __future__ import annotations

import json
from datetime import date
from sqlalchemy import text
from sqlalchemy.orm import Session


def _active_closures_count(db: Session) -> int:
    q = text("""
      SELECT COUNT(*)::int AS c
      FROM public.events_road_closed
      WHERE status = 'validated'
        AND edge_id IS NOT NULL
        AND now() >= start_time
        AND now() <= end_time
    """)
    r = db.execute(q).mappings().first()
    return int(r["c"] or 0)


def record_route_success(
    db: Session,
    start_lon: float, start_lat: float,
    end_lon: float, end_lat: float,
    vias_json,
    profile: str,
    distance_km: float,
    duration_min: float,
    edges: list[int],
    google_distance_km: float | None = None,
    google_duration_min: float | None = None,
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
            delta_distance_km, delta_duration_min
          )
          VALUES (
            :start_lon, :start_lat, :end_lon, :end_lat,
            CAST(:vias AS jsonb), :profile,
            :distance_km, :duration_min,
            :edge_count, CAST(:edges AS jsonb),
            :had, :c,
            :gdist, :gdur,
            :ddist, :ddur
          )
        """)
        db.execute(ins, {
            "start_lon": start_lon, "start_lat": start_lat,
            "end_lon": end_lon, "end_lat": end_lat,
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
        })

        # aggregation edges/day
        up = text("""
          INSERT INTO public.stats_edge_usage_daily(day, edge_id, hits, last_seen)
          VALUES (:day, :edge_id, 1, now())
          ON CONFLICT (day, edge_id) DO UPDATE
          SET hits = public.stats_edge_usage_daily.hits + 1,
              last_seen = EXCLUDED.last_seen
        """)
        d = date.today()
        params = [{"day": d, "edge_id": int(e)} for e in edges]
        if params:
            db.execute(up, params)

        db.commit()
    except Exception:
        db.rollback()


def record_route_failure(
    db: Session,
    start_lon: float | None, start_lat: float | None,
    end_lon: float | None, end_lat: float | None,
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
            "start_lon": start_lon, "start_lat": start_lat,
            "end_lon": end_lon, "end_lat": end_lat,
            "vias": json.dumps(vias_json or []),
            "profile": profile,
            "error_type": error_type,
            "error_message": error_message[:1000],
        })
        db.commit()
    except Exception:
        db.rollback()

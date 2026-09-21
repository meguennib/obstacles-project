from datetime import date, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
from .schemas import StatsSummary, StatsPoint, TimeseriesResponse, TopEdge, TopEdgesResponse, TopFailure, TopFailuresResponse


def _since_days(days: int) -> str:
    # interval string safe
    return f"{int(days)} days"


def get_summary(db: Session, days: int) -> StatsSummary:
    days = max(1, int(days))

    q_ok = text("""
        SELECT
          COUNT(*)::int AS routes_ok,
          AVG(distance_km) AS avg_distance_km,
          AVG(duration_min) AS avg_duration_min,
          SUM(CASE WHEN had_active_closures THEN 1 ELSE 0 END)::int AS with_active_closures,
          AVG(google_distance_km) AS avg_google_distance_km,
          AVG(google_duration_min) AS avg_google_duration_min,
          AVG(delta_distance_km) AS avg_delta_distance_km,
          AVG(delta_duration_min) AS avg_delta_duration_min
        FROM public.stats_route_log
        WHERE created_at >= now() - (:interval)::interval
    """)
    row_ok = db.execute(q_ok, {"interval": _since_days(days)}).mappings().first()
    routes_ok = int(row_ok["routes_ok"] or 0)
    with_active_closures = int(row_ok["with_active_closures"] or 0)

    q_fail = text("""
        SELECT COUNT(*)::int AS routes_fail
        FROM public.stats_route_fail_log
        WHERE created_at >= now() - (:interval)::interval
    """)
    row_fail = db.execute(q_fail, {"interval": _since_days(days)}).mappings().first()
    routes_fail = int(row_fail["routes_fail"] or 0)

    denom = max(1, routes_ok)
    pct = (with_active_closures * 100.0) / denom

    return StatsSummary(
        days=days,
        routes_ok=routes_ok,
        routes_fail=routes_fail,
        avg_distance_km=row_ok["avg_distance_km"],
        avg_duration_min=row_ok["avg_duration_min"],
        with_active_closures=with_active_closures,
        pct_with_active_closures=pct,
        avg_google_distance_km=row_ok["avg_google_distance_km"],
        avg_google_duration_min=row_ok["avg_google_duration_min"],
        avg_delta_distance_km=row_ok["avg_delta_distance_km"],
        avg_delta_duration_min=row_ok["avg_delta_duration_min"],
    )


def get_timeseries(db: Session, days: int) -> TimeseriesResponse:
    days = max(1, int(days))

    q = text("""
      WITH ok AS (
        SELECT date_trunc('day', created_at)::date AS d, COUNT(*)::int AS c
        FROM public.stats_route_log
        WHERE created_at >= now() - (:interval)::interval
        GROUP BY 1
      ),
      fail AS (
        SELECT date_trunc('day', created_at)::date AS d, COUNT(*)::int AS c
        FROM public.stats_route_fail_log
        WHERE created_at >= now() - (:interval)::interval
        GROUP BY 1
      )
      SELECT
        dd::date AS day,
        COALESCE(ok.c, 0)::int AS routes_ok,
        COALESCE(fail.c, 0)::int AS routes_fail
      FROM generate_series(
        (current_date - (:days - 1))::date,
        current_date::date,
        interval '1 day'
      ) AS dd
      LEFT JOIN ok ON ok.d = dd::date
      LEFT JOIN fail ON fail.d = dd::date
      ORDER BY day;
    """)
    rows = db.execute(q, {"interval": _since_days(days), "days": days}).mappings().all()

    points = [StatsPoint(day=str(r["day"]), routes_ok=r["routes_ok"], routes_fail=r["routes_fail"]) for r in rows]
    return TimeseriesResponse(days=days, points=points)


def get_top_edges(db: Session, days: int, limit: int) -> TopEdgesResponse:
    days = max(1, int(days))
    limit = max(1, min(200, int(limit)))

    q = text("""
      SELECT edge_id::int, SUM(hits)::int AS hits
      FROM public.stats_edge_usage_daily
      WHERE day >= (current_date - (:days - 1))::date
      GROUP BY edge_id
      ORDER BY hits DESC
      LIMIT :limit
    """)
    rows = db.execute(q, {"days": days, "limit": limit}).mappings().all()
    items = [TopEdge(edge_id=r["edge_id"], hits=r["hits"]) for r in rows]
    return TopEdgesResponse(days=days, items=items)


def get_top_failures(db: Session, days: int, limit: int) -> TopFailuresResponse:
    days = max(1, int(days))
    limit = max(1, min(200, int(limit)))

    q = text("""
      SELECT error_type, error_message, COUNT(*)::int AS hits
      FROM public.stats_route_fail_log
      WHERE created_at >= now() - (:interval)::interval
      GROUP BY error_type, error_message
      ORDER BY hits DESC
      LIMIT :limit
    """)
    rows = db.execute(q, {"interval": _since_days(days), "limit": limit}).mappings().all()
    items = [TopFailure(error_type=r["error_type"], error_message=r["error_message"], hits=r["hits"]) for r in rows]
    return TopFailuresResponse(days=days, items=items)

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import settings
from app.apps.routing.schemas import RouteRequest, RouteResponse, RouteComparison, GoogleCompare
from app.apps.routing.service import compute_route
from app.apps.stats.collector import record_route_success, record_route_failure
from app.apps.traffic_google.client import compute_google_route_compare

router = APIRouter(prefix="/api/v1", tags=["routing"])


@router.post("/route", response_model=RouteResponse)
def route(
    req: RouteRequest,
    compare: str | None = Query(default=None, description="Set to 'google' to compare traffic-aware duration"),
    db: Session = Depends(get_db),
):
    vias_json = [{"lon": v.lon, "lat": v.lat} for v in (req.vias or [])]

    try:
        resp: RouteResponse = compute_route(db, req)

        comparison: RouteComparison | None = None
        gdist: float | None = None
        gdur: float | None = None

        if compare == "google":
            key = settings.google_routes_api_key or ""
            if not key:
                raise HTTPException(status_code=400, detail="GOOGLE_ROUTES_API_KEY not configured")

            # Google compare: only start->end (no vias)
            gdist, gdur = compute_google_route_compare(
                api_key=key,
                start_lon=req.start.lon, start_lat=req.start.lat,
                end_lon=req.end.lon, end_lat=req.end.lat,
            )

            comparison = RouteComparison(
                google=GoogleCompare(
                    distance_km=gdist,
                    duration_min=gdur,
                    delta_distance_km=float(resp.distance_km) - float(gdist),
                    delta_duration_min=float(resp.duration_min) - float(gdur),
                )
            )

        # log success (non bloquant)
        record_route_success(
            db=db,
            start_lon=req.start.lon, start_lat=req.start.lat,
            end_lon=req.end.lon, end_lat=req.end.lat,
            vias_json=vias_json,
            profile=getattr(req, "profile", "car"),
            distance_km=float(resp.distance_km),
            duration_min=float(resp.duration_min),
            edges=list(resp.edges),
            google_distance_km=gdist,
            google_duration_min=gdur,
        )

        resp.comparison = comparison
        return resp

    except HTTPException as he:
        record_route_failure(
            db=db,
            start_lon=req.start.lon if req and req.start else None,
            start_lat=req.start.lat if req and req.start else None,
            end_lon=req.end.lon if req and req.end else None,
            end_lat=req.end.lat if req and req.end else None,
            vias_json=vias_json,
            profile=getattr(req, "profile", "car"),
            error_type="HTTPException",
            error_message=str(he.detail),
        )
        raise

    except Exception as e:
        record_route_failure(
            db=db,
            start_lon=req.start.lon if req and req.start else None,
            start_lat=req.start.lat if req and req.start else None,
            end_lon=req.end.lon if req and req.end else None,
            end_lat=req.end.lat if req and req.end else None,
            vias_json=vias_json,
            profile=getattr(req, "profile", "car"),
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e))

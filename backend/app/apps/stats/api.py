from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from .schemas import StatsSummary, TimeseriesResponse, TopEdgesResponse, TopFailuresResponse
from .service import get_summary, get_timeseries, get_top_edges, get_top_failures

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/summary", response_model=StatsSummary)
def summary(days: int = Query(7, ge=1, le=365), db: Session = Depends(get_db)):
    return get_summary(db, days)


@router.get("/timeseries", response_model=TimeseriesResponse)
def timeseries(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    return get_timeseries(db, days)


@router.get("/top-edges", response_model=TopEdgesResponse)
def top_edges(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return get_top_edges(db, days, limit)


@router.get("/top-failures", response_model=TopFailuresResponse)
def top_failures(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return get_top_failures(db, days, limit)

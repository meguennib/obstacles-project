from pydantic import BaseModel, Field
from typing import List, Optional


class StatsSummary(BaseModel):
    days: int
    routes_ok: int
    routes_fail: int
    avg_distance_km: Optional[float] = None
    avg_duration_min: Optional[float] = None
    with_active_closures: int
    pct_with_active_closures: float = 0.0
    avg_google_distance_km: float | None = None
    avg_google_duration_min: float | None = None
    avg_delta_distance_km: float | None = None
    avg_delta_duration_min: float | None = None


class StatsPoint(BaseModel):
    day: str
    routes_ok: int
    routes_fail: int


class TopEdge(BaseModel):
    edge_id: int
    hits: int


class TopFailure(BaseModel):
    error_type: str
    error_message: str
    hits: int


class TimeseriesResponse(BaseModel):
    days: int
    points: List[StatsPoint] = Field(default_factory=list)


class TopEdgesResponse(BaseModel):
    days: int
    items: List[TopEdge] = Field(default_factory=list)


class TopFailuresResponse(BaseModel):
    days: int
    items: List[TopFailure] = Field(default_factory=list)

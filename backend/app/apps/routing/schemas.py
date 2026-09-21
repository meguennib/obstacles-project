from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional


class LatLng(BaseModel):
    lon: float
    lat: float


class RouteRequest(BaseModel):
    start: LatLng
    end: LatLng
    vias: List[LatLng] = Field(default_factory=list)
    profile: str = "car"


class GoogleCompare(BaseModel):
    distance_km: float
    duration_min: float
    delta_distance_km: float
    delta_duration_min: float


class RouteComparison(BaseModel):
    google: Optional[GoogleCompare] = None


class RouteResponse(BaseModel):
    distance_km: float
    duration_min: float
    edges: List[int]
    geometry_geojson: str
    comparison: Optional[RouteComparison] = None

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


class SnappedPoint(BaseModel):
    """Noeud du graphe auquel un point a été snap + distance du clic au noeud (m)."""
    lon: float
    lat: float
    dist_m: float


class RouteResponse(BaseModel):
    distance_km: float
    duration_min: float
    edges: List[int]
    geometry_geojson: Optional[str] = None
    comparison: Optional[RouteComparison] = None
    # --- v1.2 (additifs) ---
    # Noeuds snap pour start/vias/end (ordre des points de la requête)
    snapped: Optional[List[SnappedPoint]] = None
    # Algorithme(s) utilisés ("dijkstra", "astar" ou "astar/dijkstra")
    algo: Optional[str] = None
    # Segments servis par le cache
    cache_hits: int = 0
    # Edges empruntés en mode "penalty" (évitement doux)
    used_penalized_edges: int = 0

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional, List


class RoadClosedCreate(BaseModel):
    reason: Optional[str] = None
    start_time: datetime
    # v1.2: end_time nullable = fermeture "jusqu'à nouvel ordre"
    end_time: Optional[datetime] = None
    geometry_wkt: str
    edge_id: Optional[int] = None
    # v1.2: à la validation, dériver tous les edges intersectés par geometry_wkt
    derive_from_geom: bool = False
    # v1.2 (P2): sens de la fermeture (forward = sens source->target osm2po)
    direction: Literal["both", "forward", "reverse"] = "both"
    # v1.2 (P2): mode d'évitement (block = exclusion, penalty = sur-coût)
    mode: Literal["block", "penalty"] = "block"
    penalty_factor: float = Field(default=5.0, ge=1.0, le=100.0)


class RoadClosedOut(BaseModel):
    id: int
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    reason: Optional[str] = None
    edge_id: Optional[int] = None
    derive_from_geom: bool = False
    direction: str = "both"
    mode: str = "block"
    penalty_factor: float = 5.0
    affected_edges: int = 0


class RoadClosedDetailOut(RoadClosedOut):
    geometry_wkt: Optional[str] = None
    derived_edges: Optional[List[int]] = None

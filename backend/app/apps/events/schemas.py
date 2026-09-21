from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class RoadClosedCreate(BaseModel):
    reason: Optional[str] = None
    start_time: datetime
    end_time: datetime
    geometry_wkt: str
    edge_id: Optional[int] = None


class RoadClosedOut(BaseModel):
    id: int
    status: str
    start_time: datetime
    end_time: datetime
    reason: Optional[str] = None
    edge_id: Optional[int] = None


class RoadClosedDetailOut(RoadClosedOut):
    geometry_wkt: Optional[str] = None

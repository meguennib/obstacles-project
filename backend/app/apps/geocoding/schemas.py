from pydantic import BaseModel, Field
from typing import List, Optional


class GeocodeItem(BaseModel):
    label: str
    lon: float
    lat: float
    commune: Optional[str] = None
    wilaya: Optional[str] = None


class SuggestResponse(BaseModel):
    items: List[GeocodeItem] = Field(default_factory=list)


class ReverseResponse(BaseModel):
    item: Optional[GeocodeItem] = None

from fastapi import APIRouter, HTTPException, Query

from .schemas import SuggestResponse, ReverseResponse
from .service import suggest as geocode_suggest, reverse as geocode_reverse

router = APIRouter(prefix="/api/v1/geocode", tags=["geocode"])


@router.get("/suggest", response_model=SuggestResponse)
def suggest(q: str = Query(..., min_length=3), limit: int = Query(8, ge=1, le=20)):
    try:
        items = geocode_suggest(q=q, limit=limit)
        return SuggestResponse(items=items)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Geocode suggest error: {e}")


@router.get("/reverse", response_model=ReverseResponse)
def reverse(lon: float = Query(...), lat: float = Query(...)):
    try:
        item = geocode_reverse(lon=lon, lat=lat)
        return ReverseResponse(item=item)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Geocode reverse error: {e}")

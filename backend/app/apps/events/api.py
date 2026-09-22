from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.apps.events.schemas import RoadClosedCreate, RoadClosedOut, RoadClosedDetailOut
from app.apps.events.service import (
    create_road_closed,
    validate_road_closed,
    disable_road_closed,
    list_road_closed,
    get_road_closed,
)

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("/road_closed", response_model=RoadClosedOut)
def create(payload: RoadClosedCreate, db: Session = Depends(get_db)):
    try:
        return create_road_closed(db, payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Event creation error: {e}")


@router.post("/road_closed/{event_id}/validate", response_model=RoadClosedOut)
def validate(event_id: int, db: Session = Depends(get_db)):
    try:
        return validate_road_closed(db, event_id)
    except ValueError as e:
        msg = str(e)
        if "edge_id is required" in msg:
            raise HTTPException(status_code=400, detail=msg)
        if "overlap" in msg.lower():
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=404, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Event validation error: {e}")

@router.post("/road_closed/{event_id}/disable", response_model=RoadClosedOut)
def disable(event_id: int, db: Session = Depends(get_db)):
    try:
        return disable_road_closed(db, event_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Event disable error: {e}")


@router.get("/road_closed", response_model=list[RoadClosedOut])
def list_events(
    status: str | None = Query(default=None, description="draft|validated|disabled"),
    active_now: bool | None = Query(default=None, description="true: actifs maintenant, false: inactifs"),
    edge_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return list_road_closed(db, status=status, active_now=active_now, edge_id=edge_id, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List events error: {e}")


@router.get("/road_closed/{event_id}", response_model=RoadClosedDetailOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    try:
        row = get_road_closed(db, event_id)
        if not row:
            raise HTTPException(status_code=404, detail="Event not found")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get event error: {e}")

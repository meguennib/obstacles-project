from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from app.core.db import engine
from app.core.logging import setup_logging
from app.apps.routing.api import router as routing_router
from app.apps.routing.edges import router as edges_router
from app.apps.events.api import router as events_router
from app.apps.geocoding.api import router as geocoding_router
from app.apps.stats.api import router as stats_router

setup_logging()

app = FastAPI(
    title="Obstacles Routing API",
    version="1.2.0",
    description="API de calcul d'itineraires avec evitement d'obstacles (Algerie) - PostGIS + pgRouting",
)

# CORS: allow env override
extra_origins = os.getenv("CORS_ORIGINS", "").split(",")
extra_origins = [o.strip() for o in extra_origins if o.strip()]

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
] + extra_origins

# In dev/preview (Arena) we need to allow all preview hosts
allow_all = os.getenv("ALLOW_ALL_CORS", "false").lower() in ("1", "true", "yes")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(routing_router)
app.include_router(edges_router)
app.include_router(events_router)
app.include_router(geocoding_router)
app.include_router(stats_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "db": _db_status(),
    }


def _db_status() -> str:
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001
        return "error"


@app.get("/")
def root():
    return {
        "name": "Obstacles Routing API",
        "version": "1.2.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": [
            "/api/v1/route",
            "/api/v1/edges/nearest",
            "/api/v1/events/road_closed",
            "/api/v1/geocode/suggest",
            "/api/v1/geocode/reverse",
            "/api/v1/stats/summary",
        ],
    }

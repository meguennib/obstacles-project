from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import setup_logging
from app.apps.routing.api import router as routing_router
from app.apps.events.api import router as events_router
from app.apps.geocoding.api import router as geocoding_router
from app.apps.stats.api import router as stats_router

setup_logging()

app = FastAPI(title="Routing API", version="1.0.0")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",   # au cas où vite change de port
    "http://127.0.0.1:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(routing_router)
app.include_router(events_router)
app.include_router(geocoding_router)
app.include_router(stats_router)


@app.get("/health")
def health():
    return {"ok": True}

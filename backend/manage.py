import typer
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.core.db import engine
from app.apps.routing.service import compute_route
from app.apps.routing.schemas import RouteRequest
from app.apps.events.schemas import RoadClosedCreate
from app.apps.events.service import create_road_closed, validate_road_closed

app = typer.Typer(add_completion=False)

SCHEMA_SQL = """
-- Table events (si pas déjà créée)
CREATE TABLE IF NOT EXISTS public.events_road_closed (
  id SERIAL PRIMARY KEY,
  status varchar(20) NOT NULL DEFAULT 'draft',
  reason varchar(255),
  start_time timestamptz NOT NULL,
  end_time timestamptz NOT NULL,
  geom geometry(Geometry, 4326) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Ajout déterministe: edge_id (même si la table existait déjà)
ALTER TABLE public.events_road_closed
ADD COLUMN IF NOT EXISTS edge_id integer;

CREATE INDEX IF NOT EXISTS idx_events_road_closed_geom
ON public.events_road_closed USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_events_road_closed_status_time
ON public.events_road_closed (status, start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_events_road_closed_edge_id
ON public.events_road_closed (edge_id);

-- Performance routing
CREATE INDEX IF NOT EXISTS idx_algeria_2po_4pgr_geom_way
ON public.algeria_2po_4pgr USING GIST (geom_way);
"""

@app.command("check-db")
def check_db():
    with engine.connect() as conn:
        ver = conn.execute(text("SELECT version()")).scalar_one()
        postgis = conn.execute(text("SELECT postgis_version()")).scalar_one()
        pgr = conn.execute(text("SELECT pgr_version()")).scalar_one()
        typer.echo(f"OK PostgreSQL: {ver}")
        typer.echo(f"OK PostGIS: {postgis}")
        typer.echo(f"OK pgRouting: {pgr}")

        for t in ["public.algeria_2po_4pgr", "public.algeria_2po_vertex", "public.events_road_closed"]:
            exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar_one()
            typer.echo(f"Table {t}: {'OK' if exists else 'MISSING'}")

@app.command("install-schema")
def install_schema():
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))
    typer.echo("OK schema + indexes installed/updated.")

@app.command("smoke-route")
def smoke_route(
    start_lon: float = 3.04197,
    start_lat: float = 36.7525,
    end_lon: float = 3.09,
    end_lat: float = 36.73,
    via_lon: float = 3.06,
    via_lat: float = 36.745,
):
    """
    Mini-test:
      [1] route sans vias
      [2] route avec 1 via
      [3] créer + valider une fermeture (sur le 1er edge de [1]) via edge_id puis retester
    """
    with Session(engine) as db:
        # [1] sans vias
        r1 = compute_route(db, RouteRequest(
            start={"lon": start_lon, "lat": start_lat},
            end={"lon": end_lon, "lat": end_lat},
            vias=[]
        ))
        typer.echo(f"[1] no-via: km={r1.distance_km} min={r1.duration_min} edges={len(r1.edges)}")

        # [2] avec 1 via
        r2 = compute_route(db, RouteRequest(
            start={"lon": start_lon, "lat": start_lat},
            end={"lon": end_lon, "lat": end_lat},
            vias=[{"lon": via_lon, "lat": via_lat}]
        ))
        typer.echo(f"[2] via: km={r2.distance_km} min={r2.duration_min} edges={len(r2.edges)}")

        # [3] fermeture déterministe sur le 1er edge
        first_edge = int(r1.edges[0])

        # On garde la géométrie pour audit (même si l'exclusion se fait par edge_id)
        geom_wkt = db.execute(text("""
          SELECT ST_AsText(ST_LineMerge(geom_way))
          FROM public.algeria_2po_4pgr
          WHERE id = :id
        """), {"id": first_edge}).scalar_one()

        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(minutes=5)
        end_time = now_utc + timedelta(days=1)

        ev = create_road_closed(db, RoadClosedCreate(
            reason="smoke test closure (edge_id)",
            start_time=start_time,
            end_time=end_time,
            geometry_wkt=geom_wkt,
            edge_id=first_edge
        ))

        ev2 = validate_road_closed(db, ev["id"])
        typer.echo(f"[3] closure validated: id={ev2['id']} edge_id={ev2.get('edge_id')}")

        # retest après fermeture
        try:
            r3 = compute_route(db, RouteRequest(
                start={"lon": start_lon, "lat": start_lat},
                end={"lon": end_lon, "lat": end_lat},
                vias=[]
            ))
            changed = (r3.edges[:10] != r1.edges[:10])
            typer.echo(f"[3] after-closure: km={r3.distance_km} changed={changed}")
        except Exception as e:
            typer.echo(f"[3] after-closure: route failed as expected: {e}")

if __name__ == "__main__":
    app()

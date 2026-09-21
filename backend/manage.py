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
-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;
CREATE EXTENSION IF NOT EXISTS btree_gist;

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

-- Stats tables
CREATE TABLE IF NOT EXISTS public.stats_route_log (
  id SERIAL PRIMARY KEY,
  start_lon double precision,
  start_lat double precision,
  end_lon double precision,
  end_lat double precision,
  vias jsonb,
  profile varchar(20) DEFAULT 'car',
  distance_km double precision,
  duration_min double precision,
  edge_count integer,
  edges jsonb,
  had_active_closures boolean DEFAULT false,
  active_closure_count integer DEFAULT 0,
  google_distance_km double precision,
  google_duration_min double precision,
  delta_distance_km double precision,
  delta_duration_min double precision,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.stats_route_fail_log (
  id SERIAL PRIMARY KEY,
  start_lon double precision,
  start_lat double precision,
  end_lon double precision,
  end_lat double precision,
  vias jsonb,
  profile varchar(20) DEFAULT 'car',
  error_type varchar(100),
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.stats_edge_usage_daily (
  day date NOT NULL,
  edge_id integer NOT NULL,
  hits integer NOT NULL DEFAULT 1,
  last_seen timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (day, edge_id)
);

CREATE INDEX IF NOT EXISTS idx_stats_route_log_created_at
ON public.stats_route_log (created_at);

CREATE INDEX IF NOT EXISTS idx_stats_route_fail_log_created_at
ON public.stats_route_fail_log (created_at);

CREATE INDEX IF NOT EXISTS idx_stats_edge_usage_daily_day
ON public.stats_edge_usage_daily (day);

-- Optional exclusion constraint to prevent overlapping validated closures on same edge
-- Requires btree_gist. We create it only if not exists via DO block to avoid failure on existing data
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'excl_events_road_closed_no_overlap'
  ) THEN
    BEGIN
      ALTER TABLE public.events_road_closed
      ADD CONSTRAINT excl_events_road_closed_no_overlap
      EXCLUDE USING gist (
        edge_id WITH =,
        tstzrange(start_time, end_time) WITH &&
      ) WHERE (status = 'validated' AND edge_id IS NOT NULL);
    EXCEPTION WHEN others THEN
      RAISE NOTICE 'Could not create exclusion constraint (maybe overlapping data): %', SQLERRM;
    END;
  END IF;
END $$;
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

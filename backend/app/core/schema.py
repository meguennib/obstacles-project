"""Schema SQL idempotent (bootstrap).

Source de vérité pour le bootstrap du schéma:
  - exécuté par `manage.py install-schema` (idempotent, pas de downtime),
  - baseliné par Alembic (versions/0001_baseline.py) pour les évolutions futures.

Convention: TOUT est idempotent (IF NOT EXISTS / DO blocks / ADD COLUMN IF NOT EXISTS).
"""

SCHEMA_SQL = """
-- =====================================================================
-- Extensions
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- =====================================================================
-- Tables graphe osm2po (créées ici uniquement si absentes, ex: DB fraîche
-- en CI. Sur un import OSM réel, osm2po les a déjà créées -> no-op.)
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.algeria_2po_4pgr (
  id integer PRIMARY KEY,
  source integer NOT NULL,
  target integer NOT NULL,
  cost double precision NOT NULL DEFAULT 0,
  reverse_cost double precision NOT NULL DEFAULT 0,
  dynamic_cost double precision,
  dynamic_reverse_cost double precision,
  km double precision,
  kmh double precision,
  x1 double precision,
  y1 double precision,
  x2 double precision,
  y2 double precision,
  geom_way geometry(LineString, 4326)
);

CREATE TABLE IF NOT EXISTS public.algeria_2po_vertex (
  id integer PRIMARY KEY,
  node integer NOT NULL,
  the_geom geometry(Point, 4326)
);

-- =====================================================================
-- Table events (obstacles)
-- =====================================================================
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

-- v1.2: fermeture sans date de fin (end_time NULL = jusqu'à nouvel ordre).
-- tstzrange(start, NULL) = '[start, )' -> les contraintes EXCLUDE restent valides.
ALTER TABLE public.events_road_closed ALTER COLUMN end_time DROP NOT NULL;

-- v1.2: fermetures multi-edges (la géométrie de l'événement dérive les edges à la validation)
ALTER TABLE public.events_road_closed ADD COLUMN IF NOT EXISTS derive_from_geom boolean NOT NULL DEFAULT false;

-- v1.2 (P2): sens de la fermeture (forward = sens source->target osm2po)
ALTER TABLE public.events_road_closed ADD COLUMN IF NOT EXISTS direction varchar(10) NOT NULL DEFAULT 'both';

-- v1.2 (P2): mode d'évitement (block = exclusion dure, penalty = sur-coût)
ALTER TABLE public.events_road_closed ADD COLUMN IF NOT EXISTS mode varchar(10) NOT NULL DEFAULT 'block';
ALTER TABLE public.events_road_closed ADD COLUMN IF NOT EXISTS penalty_factor numeric NOT NULL DEFAULT 5;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_events_direction') THEN
    ALTER TABLE public.events_road_closed
    ADD CONSTRAINT chk_events_direction CHECK (direction IN ('both','forward','reverse'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_events_mode') THEN
    ALTER TABLE public.events_road_closed
    ADD CONSTRAINT chk_events_mode CHECK (mode IN ('block','penalty'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_events_penalty') THEN
    ALTER TABLE public.events_road_closed
    ADD CONSTRAINT chk_events_penalty CHECK (penalty_factor >= 1 AND penalty_factor <= 100);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_events_road_closed_geom
ON public.events_road_closed USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_events_road_closed_status_time
ON public.events_road_closed (status, start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_events_road_closed_edge_id
ON public.events_road_closed (edge_id);

-- v1.2: updated_at systématiquement bumpé à chaque UPDATE
-- (sert de "version" d'invalidation exacte du cache de routes)
CREATE OR REPLACE FUNCTION public.trg_set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_events_updated_at ON public.events_road_closed;
CREATE TRIGGER trg_events_updated_at
BEFORE UPDATE ON public.events_road_closed
FOR EACH ROW EXECUTE FUNCTION public.trg_set_updated_at();

-- =====================================================================
-- v1.2: liage événement -> edges (fermetures multi-edges)
-- Un événement validé exclut/penalise TOUS les edges de cette table.
-- Le routing lit cette table (flag MULTI_EDGE_CLOSURES).
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.event_edge_closure (
  event_id integer NOT NULL REFERENCES public.events_road_closed(id) ON DELETE CASCADE,
  edge_id integer NOT NULL,
  start_time timestamptz NOT NULL,
  end_time timestamptz,
  status varchar(20) NOT NULL DEFAULT 'validated',
  direction varchar(10) NOT NULL DEFAULT 'both',
  mode varchar(10) NOT NULL DEFAULT 'block',
  penalty_factor numeric NOT NULL DEFAULT 5,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (event_id, edge_id)
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'excl_eec_no_overlap') THEN
    BEGIN
      ALTER TABLE public.event_edge_closure
      ADD CONSTRAINT excl_eec_no_overlap
      EXCLUDE USING gist (
        edge_id WITH =,
        tstzrange(start_time, end_time) WITH &&
      ) WHERE (status = 'validated');
    EXCEPTION WHEN others THEN
      RAISE NOTICE 'Could not create excl_eec_no_overlap (maybe overlapping data): %', SQLERRM;
    END;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_eec_active ON public.event_edge_closure (status, start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_eec_edge ON public.event_edge_closure (edge_id);
CREATE INDEX IF NOT EXISTS idx_eec_event ON public.event_edge_closure (event_id);

-- =====================================================================
-- v1.2: cache des segments de route
-- Invalidation exacte via closure_version = MAX(updated_at) des events
-- validated/disabled (le trigger ci-dessus le bumpé à chaque changement).
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.route_cache (
  src_node integer NOT NULL,
  dst_node integer NOT NULL,
  closure_version bigint NOT NULL,
  algo varchar(10) NOT NULL,
  cost_model varchar(10) NOT NULL,
  edges jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (src_node, dst_node, closure_version, algo, cost_model)
);

CREATE INDEX IF NOT EXISTS idx_route_cache_created ON public.route_cache (created_at);

-- =====================================================================
-- Performance routing
-- =====================================================================
CREATE INDEX IF NOT EXISTS idx_algeria_2po_4pgr_geom_way
ON public.algeria_2po_4pgr USING GIST (geom_way);

-- =====================================================================
-- Stats tables
-- =====================================================================
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

-- v1.2: combien d'edges pénalisés (mode=penalty) ont été empruntés
ALTER TABLE public.stats_route_log ADD COLUMN IF NOT EXISTS used_penalized_edges integer NOT NULL DEFAULT 0;

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

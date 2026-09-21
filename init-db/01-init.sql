-- Initial DB setup for obstacles-project
-- This runs only on first container init (empty pgdata)

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Note: algeria_2po_4pgr and algeria_2po_vertex must be imported via osm2po or shp2pgsql
-- Example import (to be done manually after):
-- psql -U postgres -d routing_db -c "CREATE TABLE public.algeria_2po_4pgr (...)"
-- The manage.py install-schema will create events_road_closed + stats tables

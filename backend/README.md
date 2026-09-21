# Backend API - Obstacles Routing

FastAPI + PostgreSQL/PostGIS/pgRouting pour calcul d'itinéraires avec évitement d'obstacles (Algérie).

## Structure

```
backend/
├── app/
│   ├── main.py (FastAPI, 5 routers, CORS)
│   ├── core/
│   │   ├── config.py (pydantic-settings, POSTGRES_*, GOOGLE_ROUTES_API_KEY)
│   │   ├── db.py (engine, SessionLocal, get_db)
│   │   └── logging.py
│   └── apps/
│       ├── routing/
│       │   ├── api.py (POST /api/v1/route?compare=google)
│       │   ├── schemas.py (LatLng, RouteRequest, RouteResponse)
│       │   ├── service.py (bbox progressive, nearest node, dijkstra, summarize)
│       │   ├── edges.py (nearest_edge_smart + POST /api/v1/edges/nearest)
│       │   └── constants.py (EDGES_TABLE, SRID)
│       ├── events/
│       │   ├── api.py (CRUD road_closed)
│       │   ├── schemas.py
│       │   └── service.py (SQL brut, edge_id obligatoire pour validate)
│       ├── geocoding/
│       │   ├── api.py (/suggest, /reverse)
│       │   ├── schemas.py
│       │   └── service.py (Photon Komoot, bbox DZ, cache, throttle)
│       ├── stats/
│       │   ├── api.py (/summary, /timeseries, /top-edges, /top-failures)
│       │   ├── service.py (get_summary avec google avg fix)
│       │   ├── collector.py (record_route_success/failure, json dumps fix)
│       │   └── schemas.py
│       └── traffic_google/
│           └── client.py (Google Routes TRAFFIC_AWARE)
├── manage.py (CLI typer: check-db, install-schema, smoke-route)
├── requirements.txt (fastapi, uvicorn, sqlalchemy, psycopg[binary], httpx, typer...)
├── Dockerfile
└── .env.example
```

## Endpoints

- `POST /api/v1/route` : calcule itinéraire
  - body: `{start:{lon,lat}, end:{lon,lat}, vias:[{lon,lat}], profile:"car"}`
  - query: `?compare=google` (nécessite GOOGLE_ROUTES_API_KEY)
  - retour: `{distance_km, duration_min, edges:[], geometry_geojson, comparison?}`

- `POST /api/v1/edges/nearest` : sélection intelligente d'edge
  - body: `{lon, lat, zoom}`
  - retour: `{edge_id, distance_m, threshold_m, accepted, geometry_wkt, geometry_geojson}`

- Events: `POST /road_closed`, `POST /{id}/validate`, `POST /{id}/disable`, `GET /road_closed`, `GET /{id}`

- Geocode: `GET /suggest?q&limit`, `GET /reverse?lon&lat`

- Stats: `GET /summary?days`, `GET /timeseries?days`, `GET /top-edges`, `GET /top-failures`

## Logique Routing

1. `compute_bbox(points, margin_factor, min_margin, max_margin)` avec 4 trials: 0.25/0.02/0.5, 0.5/0.04/1.0, 1.0/0.08/2.0, None (full graph)
2. `nearest_graph_node_id(lon,lat)` : KNN 80 edges sur `geom_way <-> point`, puis distance géodésique vers source/target -> node garanti dans graphe
3. `edges_sql_excluding_closures(bbox)` : CTE `closed` filtre `status='validated' AND edge_id IS NOT NULL AND now() BETWEEN start_time AND end_time`, LEFT JOIN + CASE cost=-1
4. `dijkstra_edges(source,target,bbox)` : `pgr_dijkstra(sql, source, target, directed:=true)`
5. `summarize_route(edge_ids)` : `unnest WITH ORDINALITY` pour préserver ordre, `ST_MakeLine ORDER BY ord`, SUM km et km/kmh*60

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# edit .env
.venv/bin/python manage.py check-db
.venv/bin/python manage.py install-schema
.venv/bin/python manage.py smoke-route
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t obstacles-backend .
docker run -p 8000:8000 --env-file .env obstacles-backend
```

## Variables d'environnement

Voir `.env.example`.

## Tests

```bash
RUN_INTEGRATION=1 .venv/bin/pytest -v
```

## Fixes v1.1.0

- Ajout router edges manquant
- Création tables stats + exclusion constraint
- Fix collector JSON serialization
- Fix get_summary google avg
- Ajout httpx dans requirements

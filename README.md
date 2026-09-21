# obstacles-project — Routing avec obstacles (Algérie)

Application de **calcul d'itinéraires** qui évite dynamiquement les routes fermées (travaux, accidents, barrages). Stack: **FastAPI + PostGIS + pgRouting + React + Leaflet**.

## 🎯 Fonctionnalités

- **Routing** `POST /api/v1/route` : Dijkstra via `pgr_dijkstra`, bbox progressive, support vias, exclusion des edges fermés (`cost = -1`)
- **Obstacles** : CRUD fermetures `events_road_closed` (draft/validated/disabled), validation exige `edge_id`, exclusion temporelle `now() BETWEEN start_time AND end_time`
- **Sélection intelligente** `POST /api/v1/edges/nearest` : seuil dynamique `18px * meters_per_pixel * densité` (clamp 12-180m), KNN PostGIS
- **Géocodage** : Photon Komoot limité DZ bbox, cache 30j, throttling 0.3s
- **Stats** : `stats_route_log`, `stats_route_fail_log`, `stats_edge_usage_daily`, dashboard React
- **Comparaison Google** : `?compare=google` utilise Google Routes API TRAFFIC_AWARE

## 🏗️ Architecture

```
obstacles-project/
├── backend/
│   ├── app/
│   │   ├── main.py (FastAPI + CORS + 5 routers)
│   │   ├── core/ config, db, logging
│   │   └── apps/
│   │       ├── routing/ (route + edges nearest)
│   │       ├── events/ (road_closed)
│   │       ├── geocoding/ (photon)
│   │       ├── stats/ (collector + service)
│   │       └── traffic_google/ (client)
│   ├── manage.py (check-db, install-schema, smoke-route)
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/ RoutePage, EventsPage, DashboardPage
│   │   ├── components/ AddressAutocomplete, MapClickPicker
│   │   └── api.ts
│   ├── Dockerfile + nginx.conf
│   └── vite.config.ts (proxy /api)
├── docker-compose.yml (db + backend + frontend)
├── init-db/01-init.sql (postgis, pgrouting, btree_gist)
├── startup.sh / stop.sh (Linux/Mac)
├── startup.bat / stop.bat (Windows)
└── Makefile
```

## 🚀 Démarrage rapide

### Option A: Docker (recommandé)

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# Editer backend/.env (POSTGRES_*, GOOGLE_ROUTES_API_KEY)
docker compose up --build
```

- API: http://localhost:8000/docs
- Front: http://localhost:5173
- DB: localhost:5432

Puis importer les données OSM:

```bash
# Exemple osm2po (à adapter)
# 1. Télécharger algeria.osm.pbf
# 2. java -jar osm2po-core.jar prefix=algeria algeria.osm.pbf
# 3. psql -h localhost -U postgres -d routing_db -f algeria_2po_4pgr.sql
# 4. psql -h localhost -U postgres -d routing_db -f algeria_2po_4pgr_vertex.sql

# Ensuite installer schema events + stats
docker compose exec backend python manage.py install-schema
docker compose exec backend python manage.py check-db
docker compose exec backend python manage.py smoke-route
```

### Option B: Local sans Docker

Prérequis: Python 3.10+, Node 20+, PostgreSQL 16 + PostGIS + pgRouting

```bash
make install
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# Editer .env

make check-db
make install-schema
make smoke-route

# 2 terminaux:
make backend
make frontend

# Ou 1 commande:
./startup.sh
```

Linux/Mac:
```bash
chmod +x startup.sh stop.sh
./startup.sh
./stop.sh
```

Windows:
```bat
startup.bat
stop.bat
```

## ⚙️ Configuration

### backend/.env

```ini
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_SERVER=localhost
POSTGRES_PORT=5432
POSTGRES_DB=routing_db

GOOGLE_ROUTES_API_KEY= # optionnel

GEOCODER_PROVIDER=photon
GEOCODER_BASE_URL=https://photon.komoot.io
GEOCODER_USER_AGENT=obstacles-project/1.0
GEOCODER_MIN_INTERVAL_SEC=0.3
GEOCODER_CACHE_TTL_DAYS=30

LOG_LEVEL=INFO
CORS_ORIGINS=https://your-front.com
ALLOW_ALL_CORS=false
```

### frontend/.env

```ini
VITE_API_BASE=http://localhost:8000
```

## 📡 API

- `GET /` : info
- `GET /health`
- `POST /api/v1/route?compare=google` -> `{start:{lon,lat}, end:{lon,lat}, vias:[]}`
- `POST /api/v1/edges/nearest` -> `{lon, lat, zoom}` => `{edge_id, distance_m, threshold_m, accepted, geometry_wkt, geometry_geojson}`
- `POST /api/v1/events/road_closed` -> `{reason, start_time, end_time, geometry_wkt, edge_id}`
- `POST /api/v1/events/road_closed/{id}/validate`
- `POST /api/v1/events/road_closed/{id}/disable`
- `GET /api/v1/events/road_closed?status=validated&active_now=true&edge_id=123`
- `GET /api/v1/events/road_closed/{id}`
- `GET /api/v1/geocode/suggest?q=Alger&limit=8`
- `GET /api/v1/geocode/reverse?lon=3.04&lat=36.75`
- `GET /api/v1/stats/summary?days=7`
- `GET /api/v1/stats/timeseries?days=30`
- `GET /api/v1/stats/top-edges?days=7&limit=20`
- `GET /api/v1/stats/top-failures?days=30&limit=10`

## 🗄️ Schéma DB

`manage.py install-schema` crée:

- `events_road_closed(id, status, reason, start_time, end_time, geom, edge_id, created_at, updated_at)` + GIST + btree + exclusion constraint anti-chevauchement
- `stats_route_log(...)` + index
- `stats_route_fail_log(...)`
- `stats_edge_usage_daily(day, edge_id, hits, last_seen)` PK(day, edge_id)
- Index `algeria_2po_4pgr.geom_way` GIST

Tables OSM2PO attendues: `algeria_2po_4pgr(id, source, target, cost, reverse_cost, km, kmh, x1,y1,x2,y2, geom_way)`, `algeria_2po_vertex`.

## 🧪 Tests

```bash
cd backend
RUN_INTEGRATION=1 .venv/bin/pytest -v
# ou
.venv/bin/python manage.py smoke-route
```

## 🔧 Corrections apportées (v1.1.0)

- **Fix critique**: ajout router `edges` manquant dans `main.py` + implémentation endpoint `POST /api/v1/edges/nearest`
- **Fix stats**: création tables `stats_*` dans `SCHEMA_SQL`, correction `get_summary` pour inclure `avg_google_*` et `avg_delta_*`, fix JSON serialization dans `collector.py`
- **Fix CORS & Vite**: `vite.config.ts` host 0.0.0.0 + proxy /api, CORS env `ALLOW_ALL_CORS` et `CORS_ORIGINS`
- **Fix requirements**: ajout `httpx`
- **Fix CSS**: correction `index.css` (`* {box-sizing}`)
- **Ops**: ajout `docker-compose.yml`, `Dockerfile` backend/frontend, `nginx.conf`, `init-db/01-init.sql`, `startup.sh`, `stop.sh`, `Makefile`, `.env.example`
- **Docs**: README complet

## 🛣️ Roadmap

- [ ] Auth JWT pour events
- [ ] Cache Redis routing
- [ ] Profils foot/bike/car avec coûts différents
- [ ] Export GPX + isochrones `pgr_drivingDistance`
- [ ] Tests E2E Playwright + CI GitHub Actions
- [ ] Monitoring Prometheus

## 📄 Licence

MIT

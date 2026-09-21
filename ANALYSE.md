# Analyse complète - obstacles-project

**Date:** 2026-09-21
**Branche:** arena/01a0c3e5-obstacles-project
**Commit base:** 7b3ff3a

## 1. Résumé exécutif

`obstacles-project` est une application de routage pour l'Algérie qui calcule un itinéraire optimal en évitant des routes fermées. 
- Backend FastAPI + PostGIS/pgRouting
- Frontend React + Leaflet
- Modules: routing, events (obstacles), edges nearest (sélection intelligente), geocoding Photon, stats, Google Routes compare.

**État initial:** MVP fonctionnel mais avec bugs bloquants (router edges manquant, tables stats manquantes), pas de Docker, README obsolète, scripts Windows only.

**État après fix v1.1.0:** Corrigé, dockerisé, documenté, prêt à déployer.

## 2. Objectif métier

Permettre à un utilisateur de:
1. Chercher une adresse en Algérie (Photon) ou cliquer sur carte
2. Définir Start/End/Vias
3. Calculer route via pgRouting Dijkstra en évitant les fermetures validées dont la fenêtre temporelle contient `now()`
4. Créer une fermeture: sélectionner edge le plus proche (seuil dynamique px/densité/zoom), créer draft puis valider
5. Voir dashboard stats: OK/FAIL, distance/durée moyenne, comparaison Google trafic, top edges, top failures

Cas d'usage: travaux routiers, accidents, barrages, optimisation logistique.

## 3. Architecture

### 3.1 Backend

- `main.py`: FastAPI, CORS, 5 routers (routing, edges, events, geocoding, stats), /health, /
- `core/config.py`: pydantic-settings, POSTGRES_*, GOOGLE_ROUTES_API_KEY, JWT_SECRET
- `core/db.py`: SQLAlchemy engine psycopg, SessionLocal
- `core/logging.py`: basicConfig LOG_LEVEL

#### routing/
- `constants.py`: EDGES_TABLE=algeria_2po_4pgr, SRID=4326
- `schemas.py`: LatLng, RouteRequest, RouteResponse, GoogleCompare
- `service.py`:
  - BBox progressive 4 trials
  - nearest_graph_node_id: KNN 80 + endpoint distance géodésique
  - edges_sql_excluding_closures: CTE closed + CASE cost=-1
  - dijkstra_edges: pgr_dijkstra
  - summarize_route: unnest WITH ORDINALITY + ST_MakeLine ORDER BY ord
  - compute_route: chaine start->vias->end
- `edges.py` (FIX): NearestEdgeRequest/Response, _meters_per_pixel, _compute_threshold_m (18px * mpp * density_factor clamp 12-180), nearest_edge_smart (KNN 10, ST_Distance geography, stats avg), router POST /api/v1/edges/nearest
- `api.py`: POST /route?compare=google + collector

#### events/
- Table events_road_closed(id, status draft/validated/disabled, reason, start_time, end_time, geom, edge_id)
- service.py: SQL brut, create, validate (check edge_id, catch IntegrityError), disable, list (filtres status/active_now/edge_id), get
- api.py: CRUD

#### geocoding/
- service.py: Photon https://photon.komoot.io, bbox DZ -8.67,18.96,11.98,37.09, lang fr, throttle 0.3s, cache TTL 30j in-memory, hard gate countrycode DZ, parsing housenumber/street/city/state
- api.py: /suggest?q&limit, /reverse?lon&lat

#### stats/
- collector.py: record_route_success (active_closure_count, had_active_closures, google delta, edge_count, edges jsonb, vias jsonb) + upsert stats_edge_usage_daily, record_route_failure
- service.py: get_summary (FIX ajoute avg_google_*), get_timeseries (generate_series), get_top_edges, get_top_failures
- schemas.py: StatsSummary avec google fields
- api.py: /summary, /timeseries, /top-edges, /top-failures

#### traffic_google/
- client.py: Google Routes v2 computeRoutes, TRAFFIC_AWARE, FieldMask distanceMeters,duration, parse "123s"

#### manage.py
- SCHEMA_SQL (FIX): postgis, pgrouting, btree_gist extensions, events_road_closed + indexes, idx_algeria_2po_4pgr_geom_way GIST, stats_route_log, stats_route_fail_log, stats_edge_usage_daily, exclusion constraint excl_events_road_closed_no_overlap (edge_id =, tstzrange &&) WHERE validated
- check-db: version(), postgis_version(), pgr_version(), to_regclass
- install-schema: engine.begin() execute SCHEMA_SQL
- smoke-route: no-via, via, closure deterministe sur 1er edge + retest

### 3.2 Frontend

- Vite + React 19 + TS + Leaflet
- App.tsx: 3 tabs sans router
- api.ts: VITE_API_BASE, apiGet/apiPost error parsing
- types.ts: miroir backend
- RoutePage: autocomplete debounce 250ms, pick modes, compare google checkbox, geojsonToLatLngs, polylines, fitBounds, cards distance/durée
- EventsPage: grid 560px + map, AutocompleteInput inline, MapClickPicker (click -> nearest edge), selectedLines, createAndValidate (POST road_closed + validate), list + disable
- DashboardPage: filtre jours, cards, timeseries table, closures actives, top edges/failures, useMemo totals
- components/AddressAutocomplete, MapClickPicker, utils/geo.ts
- vite.config.ts (FIX): host 0.0.0.0, proxy /api -> localhost:8000, preview host
- index.css (FIX): * box-sizing + styles de base

### 3.3 Base de données

- algeria_2po_4pgr (osm2po): id, source, target, cost, reverse_cost, dynamic_cost, dynamic_reverse_cost, km, kmh, x1,y1,x2,y2, geom_way
- algeria_2po_vertex
- events_road_closed (par manage.py)
- stats_route_log, stats_route_fail_log, stats_edge_usage_daily (par manage.py FIX)

## 4. Flux

**Routing:** User pick -> POST /route -> nearest nodes -> Dijkstra bbox trials -> summarize -> GeoJSON -> Leaflet

**Fermeture:** User adresse/clic -> POST /edges/nearest zoom -> si accepted -> POST /road_closed draft + geom + edge_id -> validate -> status validated -> prochaines routes excluent si now() in range

**Stats:** chaque route logguée

## 5. Points forts

- Algo routing robuste (bbox progressive, KNN endpoint, -1 exclusion, ORDINALITY)
- Sélection edge intelligente (seuil px/m/densité/zoom)
- Geocoding DZ-first + cache + throttle
- Observabilité (stats, smoke-route, health)
- Frontend pragmatique Leaflet
- Séparation apps claire

## 6. Points faibles initiaux

- README racine listait 2 modules sur 5, frontend README template Vite
- Pas de .env.example, pas de Docker, pas de migrations Alembic
- edges router manquant -> 404
- stats tables manquantes -> rollback silencieux
- get_summary ne retournait pas google avg
- collector JSON serialization bug (list -> jsonb)
- requirements sans httpx
- index.css invalide
- vite.config sans host/proxy
- CORS hardcodé localhost
- startup.bat Windows only
- .gitignore incomplet
- Pas de tests, pas d'auth, pas de rate limiting, pas de cache Redis
- Exclusion constraint manquante -> chevauchement possible

## 7. Bugs détectés

1. POST /api/v1/edges/nearest 404 (router non inclus)
2. stats tables manquantes
3. Dashboard Google avg toujours null
4. Overlap closures possible
5. MapContainer ref hack
6. Date ISO UTC vs now() server tz
7. index.css bloc {} invalide

## 8. Corrections v1.1.0 (fait)

### Backend
- [x] edges.py: ajout router APIRouter + 2 endpoints POST /nearest et /nearest/ (slash alias)
- [x] main.py: include edges_router, CORS env ALLOW_ALL_CORS + CORS_ORIGINS, root / info, health version
- [x] manage.py SCHEMA_SQL: extensions postgis/pgrouting/btree_gist, stats tables, indexes, exclusion constraint avec DO block safe
- [x] stats/service.py: SELECT avg_google_* + avg_delta_*
- [x] stats/collector.py: import json, json.dumps(vias, edges), CAST(:edges AS jsonb)
- [x] requirements.txt: ajout httpx

### Frontend
- [x] vite.config.ts: host 0.0.0.0, proxy /api, preview host
- [x] index.css: fix * box-sizing + styles de base

### Ops / Docs
- [x] docker-compose.yml: db postgis:16-3.4 + backend (uvicorn reload) + frontend (nginx multi-stage), pgdata volume, healthcheck, env_file
- [x] backend/Dockerfile: python:3.12-slim + gcc libpq-dev
- [x] frontend/Dockerfile: node:20-alpine builder + nginx:alpine prod, ARG VITE_API_BASE
- [x] frontend/nginx.conf: SPA fallback + proxy /api/ -> backend:8000 + gzip
- [x] init-db/01-init.sql: extensions
- [x] backend/.env.example + frontend/.env.example
- [x] startup.sh + stop.sh (Linux/Mac, chmod +x)
- [x] Makefile: install, backend, frontend, dev, check-db, install-schema, smoke-route, docker-up/down, lint
- [x] .gitignore: pgdata, .env.local, logs, DS_Store, etc.
- [x] README.md racine complet + backend/README.md + frontend/README.md

### Vérifications
- [x] py_compile OK
- [x] npm run build OK (80 modules, 377kB js, 117kB gzip)

## 9. Recommandations P1/P2

**P1:**
- React Router + Zustand
- Un seul AddressAutocomplete
- Tests E2E Playwright + GitHub Actions
- .env validation via pydantic
- Rate limiting + cache Redis

**P2:**
- Auth JWT admin events
- Profils foot/bike/car coûts différents
- Export GPX, isochrones pgr_drivingDistance
- Monitoring Prometheus + Grafana
- Alembic migrations

## 10. Comment tester

```bash
# Docker
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose up --build
# Import OSM2PO algeria_2po_4pgr
docker compose exec backend python manage.py install-schema
docker compose exec backend python manage.py smoke-route
# Open http://localhost:5173 et http://localhost:8000/docs

# Local
make install
make check-db
make install-schema
./startup.sh
```

## 11. Conclusion

Projet pertinent pour Algérie, algo routing au-dessus de la moyenne, sélection edge intelligente excellente. Après fix v1.1.0, il est déployable, dockerisé, documenté. Reste à ajouter auth, cache, tests pour prod.

# obstacles-project — Routing avec obstacles (Algérie)

Application de **calcul d'itinéraires** qui évite dynamiquement les routes fermées (travaux, accidents, barrages). Stack: **FastAPI + PostGIS + pgRouting + React + Leaflet**.

## 🎯 Fonctionnalités

- **Routing** `POST /api/v1/route` : Dijkstra/A* via pgRouting, bbox progressive (4 essais + graphe complet), support vias, exclusion des edges fermés (`cost = -1`)
  - **v1.2** : modèle de coût `time` (trajet le plus rapide, minutes) ou `distance` (comportement d'origine), A* admissible (UTM) pour les longs trajets avec repli Dijkstra, cache de segments à invalidation exacte, réponse enrichie (`snapped`, `algo`, `cache_hits`, `used_penalized_edges`) + headers `X-Route-Algo` / `X-Route-Cache`
- **Obstacles** : CRUD fermetures `events_road_closed` (draft/validated/disabled), validation exige `edge_id`, exclusion temporelle `now() BETWEEN start_time AND end_time`
  - **v1.2** : fermetures **multi-edges** dérivées de la géométrie (`derive_from_geom`, table `event_edge_closure`, anti-chevauchement EXCLUDE → 409), `end_time` nullable (« jusqu'à nouvel ordre »), **sens** de fermeture (`both`/`forward`/`reverse`), **mode pénalité** (évitement doux, sur-coût ×facteur) au lieu du blocage
- **Sélection intelligente** `POST /api/v1/edges/nearest` : seuil dynamique `18px * meters_per_pixel * densité` (clamp 12-180m), KNN PostGIS — le snap du routing est batché (1 requête) et **directionnel** (anti U-turn, v1.2)
- **Géocodage** : Photon Komoot limité DZ bbox, cache 30j, throttling 0.3s
- **Stats** : `stats_route_log`, `stats_route_fail_log`, `stats_edge_usage_daily`, dashboard React
- **Comparaison Google** : `?compare=google` utilise Google Routes API TRAFFIC_AWARE
- **Ops** : `Makefile` (install/dev/test/bench/smoke-route), graphe de test déterministe 12×12, bench p50/p95, Alembic (baseline), CI GitHub Actions (PostGIS + tests + bench artifact)

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
│   ├── manage.py (check-db, install-schema, make-test-graph, smoke-route, bench-route)
│   ├── alembic/ (versionnement du schéma, baseline 0001)
│   ├── tests/ (unitaires SQL/builders + intégration grid déterministe)
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/ RoutePage, EventsPage, DashboardPage
│   │   ├── components/ AddressAutocomplete, MapClickPicker, MapDrawPicker
│   │   └── api.ts
│   ├── Dockerfile + nginx.conf
│   └── vite.config.ts (proxy /api)
├── docker-compose.yml (db + backend + frontend)
├── init-db/01-init.sql (postgis, pgrouting, btree_gist)
├── .github/workflows/ci.yml (CI: PostGIS service + tests + bench)
├── startup.sh / stop.sh (Linux/Mac)
├── startup.bat / stop.bat (Windows)
├── Makefile (install/dev/test/bench/smoke-route/…)
└── ROADMAP.md (feuille de route v1.2 — implémentée)
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

# --- v1.2: routing (rollback instantané = remettre les valeurs d'origine) ---
COST_MODEL=time            # time (défaut v1.2, minutes) | distance (origine)
ROUTING_ALGO=auto          # auto (Dijkstra court / A* >= seuil) | dijkstra | astar
ASTAR_LONG_ROUTE_KM=40     # seuil d'activation d'A* en mode auto
ROUTE_CACHE=true           # cache des segments (invalidation exacte)
ROUTE_CACHE_TTL_MIN=10
ROUTE_CACHE_RETENTION_HOURS=6
MULTI_EDGE_CLOSURES=true   # false = comportement d'origine (edge_id seul)

DB_POOL_SIZE=20            # pool de connexions (v1.2)
DB_POOL_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=5

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
- `GET /health` : état + connectivité DB
- `POST /api/v1/route?compare=google` -> `{start:{lon,lat}, end:{lon,lat}, vias:[]}`
  - **v1.2 réponse enrichie (additive)** : `snapped[]` (noeud de snap + offset en m par point), `algo` (`dijkstra`/`astar`/`astar/dijkstra`), `cache_hits`, `used_penalized_edges` + headers `X-Route-Algo` / `X-Route-Cache` (`hit`/`miss`/`disabled`)
- `POST /api/v1/edges/nearest` -> `{lon, lat, zoom}` => `{edge_id, distance_m, threshold_m, accepted, geometry_wkt, geometry_geojson}`
- `POST /api/v1/events/road_closed` -> `{reason, start_time, end_time?, geometry_wkt, edge_id?, derive_from_geom?, direction?, mode?, penalty_factor?}`
  - **v1.2** : `end_time` nullable (jusqu'à nouvel ordre), `derive_from_geom=true` + LINESTRING → tous les edges traversés sont exclus à la validation (plafond 500), `direction` (`both`/`forward`/`reverse`), `mode` (`block`/`penalty` ×`penalty_factor` 1–100)
- `POST /api/v1/events/road_closed/{id}/validate` → 409 si chevauchement validé sur le même edge/fenêtre
- `POST /api/v1/events/road_closed/{id}/disable`
- `GET /api/v1/events/road_closed?status=validated&active_now=true&edge_id=123` (v1.2 : `active_now` gère `end_time` NULL)
- `GET /api/v1/events/road_closed/{id}` (v1.2 : + `derived_edges[]`, `affected_edges`)
- `GET /api/v1/geocode/suggest?q=Alger&limit=8`
- `GET /api/v1/geocode/reverse?lon=3.04&lat=36.75`
- `GET /api/v1/stats/summary?days=7`
- `GET /api/v1/stats/timeseries?days=30`
- `GET /api/v1/stats/top-edges?days=7&limit=20`
- `GET /api/v1/stats/top-failures?days=30&limit=10`

## 🗄️ Schéma DB

`manage.py install-schema` crée (idempotent, aussi versionné en Alembic `0001_baseline`):

- `events_road_closed(id, status, reason, start_time, end_time?, geom, edge_id?, derive_from_geom?, direction?, mode?, penalty_factor?, created_at, updated_at)` + GIST + btree + exclusion constraint anti-chevauchement (v1.2 : `end_time` nullable, colonnes multi-edges/sens/pénalité, trigger `updated_at`)
- `event_edge_closure(event_id, edge_id, start_time, end_time?, status, direction, mode, penalty_factor)` UNIQUE(event_id, edge_id) + EXCLUDE anti-chevauchement validé (v1.2)
- `route_cache(src_node, dst_node, closure_version, algo, cost_model, edges jsonb, created_at)` PK composite (v1.2)
- `stats_route_log(..., used_penalized_edges)` + index
- `stats_route_fail_log(...)`
- `stats_edge_usage_daily(day, edge_id, hits, last_seen)` PK(day, edge_id)
- Index `algeria_2po_4pgr.geom_way` GIST (KNN)

Tables OSM2PO attendues: `algeria_2po_4pgr(id, source, target, cost, reverse_cost, km, kmh, x1,y1,x2,y2, geom_way)`, `algeria_2po_vertex`.

## 🧪 Tests

```bash
# Unitaires (sans DB: builders SQL validés par pglast, coûts, bbox, snap…)
make test

# Intégration (DB PostGIS + graphe de test déterministe 12×12)
make install-schema make-test-graph
make test-integration        # RUN_INTEGRATION=1 + -m integration

# Mini-smoke (routing, via, fermeture, nettoyage)
make smoke-route

# Benchmark p50/p95 (sans/avec fermetures) -> docs/benchmarks/
make bench
```

- `backend/tests/` : unitaires purs (SQL syntaxique via **pglast**, expressions de coût, CTE obstacles, choix d'algorithme, UTM, bbox, direction de snap) + intégration déterministe sur le **grid synthétique** (`manage.py make-test-graph`) : détour après fermeture, firewall multi-edges (400), pénalité (2 edges comptés), sens `forward`, snap directionnel, cache hit/invalidation.
- **CI** (`.github/workflows/ci.yml`) : service `postgis/postgis:16-3.4` → install-schema → make-test-graph → check-db → smoke-route → `pytest` (unitaires + intégration) → bench artifact ; job frontend : `npm ci` → build → lint.

## ✨ Nouveautés v1.2.0 (feuille de route ROADMAP.md — jalons M0→M3)

**Routing plus rapide et plus pertinent (P0)**
- Modèle de coût `time` : `km/kmh×60` (minutes) — la route retournée est la plus RAPIDE ; `dynamic_cost` manuel reste prioritaire ; repli `distance` (comportement d'origine) si `kmh` nul. Flag `COST_MODEL`.
- A* (`pgr_astar`) pour les segments ≥ `ASTAR_LONG_ROUTE_KM` (mode `auto`), heuristique **admissible** (coordonnées UTM projetées par zone, facteur `0.06/v_cap` en temps ; `0.001` en distance ; 70 km/deg conservateur sur graphe complet) ; repli Dijkstra systématique si échec. Flag `ROUTING_ALGO` (`auto`/`dijkstra`/`astar`).
- Snap batché : **1 seule requête** pour start+vias+end (fin du N+1) — KNN GiST (80 edges), endpoints des 8 premiers, distance géodésique, sélection **directionnelle** anti U-turn (produit scalaire avec le sens de voyage).

**Mise à l'échelle & obstacles enrichis (P1)**
- Cache des segments `route_cache` : clé `(src, dst, closure_version, algo, cost_model)`, **invalidation exacte** par version = `MAX(updated_at)` des événements validés/désactivés (trigger), TTL 10 min, rétention 6 h, échecs non bloquants. Flag `ROUTE_CACHE`. Réponse : `cache_hits`, header `X-Route-Cache`.
- Fermetures **multi-edges** : `derive_from_geom` + LINESTRING → tous les edges intersectés/touchés (pré-filtre GiST buffer 0.002°, plafond 500) dans `event_edge_closure` ; anti-chevauchement par contrainte EXCLUDE → **409**. Flag `MULTI_EDGE_CLOSURES` (false = CTE d'origine sur `edge_id`).
- `end_time` nullable = « jusqu'à nouvel ordre » (`tstzrange(start, NULL)`, `active_now` adapté).
- Frontend EventsPage : mode **Point** (origine) / **Tracé** (double-clic termine), champs sens/évitement/pénalité, colonne « edges (tracé) » ; RoutePage : connecteurs pointillés clic→noeud snap (offset > 5 m), infos algo/cache/décalage/edges pénalisés.

**Finitions (P2)**
- **Sens** de fermeture : `forward` bloque `cost`, `reverse` bloque `reverse_cost` (la route peut emprunter l'autre sens).
- **Pénalité** : `mode=penalty` ×`penalty_factor` (sur-coût, évitement doux) ; réponse `used_penalized_edges`.
- **Alembic** : baseline `0001` (le SQL de bootstrap reste la source de vérité idempotente).
- Pool de connexions (`DB_POOL_*`), `/health` avec état DB, graphe de test déterministe + bench + CI.

**Rollback** : chaque brique est réversible par flag env (voir Configuration) — aucun champ d'API retiré (ajouts uniquement).

## 🔧 Corrections apportées (v1.1.0)

- **Fix critique**: ajout router `edges` manquant dans `main.py` + implémentation endpoint `POST /api/v1/edges/nearest`
- **Fix stats**: création tables `stats_*` dans `SCHEMA_SQL`, correction `get_summary` pour inclure `avg_google_*` et `avg_delta_*`, fix JSON serialization dans `collector.py`
- **Fix CORS & Vite**: `vite.config.ts` host 0.0.0.0 + proxy /api, CORS env `ALLOW_ALL_CORS` et `CORS_ORIGINS`
- **Fix requirements**: ajout `httpx`
- **Fix CSS**: correction `index.css` (`* {box-sizing}`)
- **Ops**: ajout `docker-compose.yml`, `Dockerfile` backend/frontend, `nginx.conf`, `init-db/01-init.sql`, `startup.sh`, `stop.sh`, `Makefile`, `.env.example`
- **Docs**: README complet

## 🛣️ Roadmap

- [x] CI GitHub Actions (PostGIS + tests unitaires/intégration + bench artifact) — v1.2
- [ ] Tests E2E Playwright
- [ ] Auth JWT pour events
- [ ] Cache Redis routing (le cache SQL local couvre l'usage mononœud)
- [ ] Profils foot/bike/car avec coûts différents
- [ ] Export GPX + isochrones `pgr_drivingDistance`
- [ ] Monitoring Prometheus

## 📄 Licence

MIT

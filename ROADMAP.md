# Feuille de route — Améliorations routing & obstacles

**Date:** 2026-09-21
**Scope:** backend (FastAPI + PostGIS/pgRouting) + frontend (React + Leaflet)
**Principe:** aucun changement cassant — additions uniquement, flags de rollback sur chaque brique.

> ## ✅ Statut (2026-09-21) : implémentée — v1.2.0
> Jalons **M0 → M3 tous livrés** : bench + grid déterministe, coût temps + A* admissible,
> cache à invalidation exacte, fermetures multi-edges/sens/pénalité, snap batché directionnel,
> pool de connexions, Alembic baseline, CI GitHub Actions (PostGIS + tests + bench artifact),
> frontend EventsPage (Point/Tracé) + RoutePage (infos snap/algo/cache).
> Validation locale : 24 tests unitaires verts (SQL validé par pglast), attendus d'intégration
> **vérifiés par simulation exacte du graphe** ; build frontend propre.
> Tests d'intégration + bench s'exécutent en CI (PostGIS requis).

---

## 0. Objectifs & invariants (ce qui ne change JAMAIS)

| Invariant | Justification |
|---|---|
| Contrat `POST /api/v1/route` : mêmes champs (`distance_km`, `duration_min`, `edges`, `geometry_geojson`, `comparison`) — ajouts seulement | Le frontend existant continue de fonctionner tel quel |
| Dijkstra reste disponible (routes courtes + repli systématique d'A*) | Garanti de justesse sur le cas local |
| Workflow événements `draft → validated → disabled` | Mécanisme métier existant |
| `/api/v1/edges/nearest` + seuil dynamique (18 px × mpp × densité, clamp 12–180 m) | Sélection intelligente déjà validée |
| Schéma Postgres additif et idempotent (pattern `manage.py install-schema`), pas de perte de données | Déploiement sans downtime |
| Frontend : mêmes 3 pages, pas de réécriture | Composants existants conservés |
| Chaque brique derrière un flag env (`COST_MODEL`, `ROUTING_ALGO`, `ROUTE_CACHE`, `MULTI_EDGE_CLOSURES`) | Rollback instantané en production |

---

## 1. Phase 0 — Baseline de mesure (avant tout changement d'algorithme)

Objectif : pouvoir quantifier « avant / après » sur le même jeu de données.

**Backend**
- Nouveau : commande `manage.py bench-route`
  - Matrice de trajets fixes et documentés : 3 urbains (Alger, Oran, Constantine), 3 régionaux, 2 interurbains longs (Oran→Alger, Oran→Constantine), chacun testé (a) sans fermeture, (b) avec 5 fermetures validées le long du tracé.
  - Pour chaque trajet : 20 exécutions → p50, p95, moyenne (latence API complète et temps SQL Dijkstra séparés via `EXPLAIN ANALYZE` logué).
  - Sortie JSON → `docs/benchmarks/<date>_<algo>.json` + affichage tableau.
- Nouveau : `docs/benchmarks/baseline.json` = mesures du système actuel (committé comme référence).

**Frontend :** aucun changement.

**Critère d'acceptation :** baseline commitée, reproductible (`make bench`), le même run donne des latences ±10 %.

**Effort :** S (0,5 j)

---

## 2. Phase 1 (P0) — Routing plus rapide et plus pertinent (backend pur)

### 2.1 Modèle de coût = temps (au lieu de distance)

**Constat :** `pgr_dijkstra` optimise `COALESCE(dynamic_cost, cost)` = distance osm2po ; la durée n'est calculée qu'après coup (`km/kmh×60`). Une route la plus courte n'est pas la plus rapide.

**Changements backend**
- Nouveau fichier `backend/app/apps/routing/costs.py` :
  - `time_cost_sql()` → expression SQL : `CASE WHEN e.kmh > 0 THEN e.km / e.kmh * 60.0 ELSE e.km END` (minutes ; repli distance si `kmh` nul).
  - `build_cost_expr(direction: "cost" | "reverse_cost")` → `COALESCE(e.dynamic_cost, <time_expr>)` (et idem reverse) : l'override `dynamic_cost` manuel reste prioritaire.
  - `get_v_cap(db)` → `MAX(kmh) WHERE kmh > 0` sur le graphe, mis en cache in-process (TTL 5 min). Sert à A* (ci-dessous).
- Modifié `routing/service.py` : `edges_sql_excluding_closures()` utilise `build_cost_expr` au lieu de `COALESCE(dynamic_cost, cost)`.
- Modifié `core/config.py` + `backend/.env.example` : `COST_MODEL=time|distance` (défaut `time`).
- `summarize_route` inchangé (la durée affichée devient alors cohérente avec l'objectif de recherche).

**API :** contrat inchangé. Valeur sémantique : `duration_min` ≈ objectif de Dijkstra.

**Frontend :** aucun changement.

**Tests**
- Test de cohérence : sur un échantillon de paires, la durée du chemin obtenu en `time` ≤ durée du chemin obtenu en `distance` (± marge).
- Test de repli : `kmh = NULL` sur un edge → pas d'erreur, coût distance.

**Risque / rollback :** changement de comportement (tracés différents) → `COST_MODEL=distance` restaure l'ancien comportement exact.

**Effort :** S (0,5 j)

### 2.2 A* pour les trajets longs (repli Dijkstra)

**Constat :** Dijkstra explore tout le sous-graphe ; sur l'interurbain (bbox essais 2–3) c'est le principal coût.

**Changements backend**
- Modifié `routing/service.py` :
  - Nouvelle fonction `astar_edges(db, source, target, bbox, heur_scale)` :
    - `pgr_astar($$ <edges_sql> $$, :source, :target, directed := true, heur := :heur_scale)` (pgRouting 3.x, déjà imposé par l'usage de la syntaxe sous-requête).
    - La sous-requête d'edges est enrichie des coordonnées projetées **UTM** de la zone de la bbox du trajet (SRID `32629` / `32630` / `32631` selon la longitude du centroïde — couvre toute l'Algérie) : `ST_X(ST_StartPoint(ST_Transform(e.geom_way, :zone)))` etc. → heuristique quasi admissible (distorsion UTM < 0,5 %, le chemin reste optimal ou quasi).
    - `heur_scale = 3.6 / v_cap` (coût en minutes, coordonnées en mètres) : `h(n) = dist_UTM(n, cible) / v_cap` ≤ temps réel de tout chemin valide → admissible.
  - Nouvelle fonction `route_segment(db, a, b, bbox)` : dispatch —
    - distance à vol d'oiseau `a→b` < `ASTAR_LONG_ROUTE_KM` (défaut **40**) → `dijkstra_edges` (inchangé, sous-graphe restreint, résultat exact) ;
    - sinon → `astar_edges` ; si A* renvoie vide/erreur → **repli automatique `dijkstra_edges`** (log warning).
  - Essais bbox pour A* : 2 essais (facteur 0,5 puis 1,0) + graphe complet, au lieu de 4 (A* tolère mieux les bboxes larges).
- Modifié `core/config.py` + `.env.example` : `ROUTING_ALGO=auto|dijkstra|astar` (défaut `auto` = dispatch par distance), `ASTAR_LONG_ROUTE_KM=40`.
- Header de réponse (additif, optionnel) : `X-Route-Algo: dijkstra|astar` (aide au bench et au debug).

**API :** contrat inchangé (header optionnel uniquement).

**Frontend :** aucun changement.

**Tests**
- Test de qualité : sur 100 paires de nœuds aléatoires où les deux algorithmes trouvent un chemin : `duration(A*) ≤ duration(Dijkstra) × 1.02`.
- Test de repli : forcer un cas où A* échoue (bbox trop étroite) → résultat Dijkstra.
- Test d'admissibilité unitaire : `heur_scale` calculé avec `v_cap` réel.
- Benchmark : p95 trajets interurbains avec/fermetures vs `baseline.json`.

**Risque / rollback :** A* légèrement suboptimal sur cas extrêmes (fermetures qui allongent énormément) → repli Dijkstra + contrôle qualité au bench ; `ROUTING_ALGO=dijkstra` = comportement d'origine exact.

**Effort :** M (1,5–2 j)

**Critère d'acceptation Phase 1 :** p95 interurbain ≤ 50 % de la baseline ; qualité de route ≤ 2 % de dégradation ; 100 % de la suite de tests verte.

---

## 3. Phase 2 (P1) — Mise à l'échelle & modèle d'obstacles enrichi

### 3.1 Cache des segments de route

**Constat :** aucune mémorisation ; deux requêtes identiques recalculent tout.

**Changements backend**
- Nouveau (schema, `manage.py install-schema`, idempotent) :
  ```sql
  CREATE TABLE IF NOT EXISTS public.route_cache (
    src_node integer NOT NULL,
    dst_node integer NOT NULL,
    closure_version timestamptz NOT NULL,
    algo varchar(10) NOT NULL,
    distance_km double precision NOT NULL,
    duration_min double precision NOT NULL,
    edges jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (src_node, dst_node, closure_version, algo)
  );
  -- Trigger : bump updated_at sur TOUT update d'event (aujourd'hui absent)
  CREATE OR REPLACE FUNCTION trg_set_updated_at() ...;
  CREATE TRIGGER ... BEFORE UPDATE ON public.events_road_closed ...;
  ```
  - `closure_version` = `MAX(updated_at) WHERE status IN ('validated','disabled')` (les drafts n'impactent pas le routing → pas d'invalidation inutile).
- Modifié `routing/service.py` :
  - Avant calcul d'un segment `(a→b)` : `SELECT edges FROM route_cache WHERE ... AND closure_version = (version courante) AND created_at > now() - interval '10 minutes'` → hit : on réutilise `edges` + métriques (la géo est recalculée par `summarize_route`, ~1 ms).
  - Après calcul : `INSERT ... ON CONFLICT DO NOTHING`.
  - Nettoyage opportuniste : `DELETE WHERE created_at < now() - interval '6 hours'` (1× par requête, table petite).
- Modifié `core/config.py` : `ROUTE_CACHE=on|off` (défaut `on`).
- Header additif : `X-Route-Cache: hit|miss|disabled`.

**Frontend :** aucun changement.

**Tests**
- Hit : 2ᵉ requête identique ≥ 10× plus rapide que la 1ʳᵉ.
- Invalidation : créer une fermeture validée sur le tracé → la requête suivante renvoie le **détour** (pas le cache).
- `ROUTE_CACHE=off` → comportement d'origine.

**Effort :** M (1–1,5 j)

### 3.2 Fermetures multi-edges dérivées de la géométrie

**Constat :** `edge_id` est singulier et la `geom` de l'événement n'est JAMAIS utilisée par le routing. Un chantier de 3 km traverse ~20 edges → 20 fermetures manuelles aujourd'hui.

**Changements backend**
- Nouveau (schema) :
  ```sql
  CREATE TABLE IF NOT EXISTS public.event_edge_closure (
    event_id integer NOT NULL REFERENCES public.events_road_closed(id) ON DELETE CASCADE,
    edge_id integer NOT NULL,
    start_time timestamptz NOT NULL,
    end_time timestamptz NOT NULL,
    status varchar(20) NOT NULL,
    UNIQUE (event_id, edge_id),
    CONSTRAINT excl_eec_no_overlap EXCLUDE USING gist (
      edge_id WITH =,
      tstzrange(start_time, end_time) WITH &&
    ) WHERE (status = 'validated')
  );
  CREATE INDEX IF NOT EXISTS idx_eec_active ON public.event_edge_closure (status, start_time, end_time);
  CREATE INDEX IF NOT EXISTS idx_eec_edge ON public.event_edge_closure (edge_id);
  ```
- Modifié `events/service.py` :
  - `validate_road_closed` : après vérification `edge_id` (invariant), si `derive_from_geom` (ou `geom` ≠ géométrie de l'edge anchor) :
    ```sql
    INSERT INTO event_edge_closure(event_id, edge_id, start_time, end_time, status)
    SELECT :id, e.id, :start, :end, 'validated'
    FROM algeria_2po_4pgr e
    WHERE e.geom_way && ST_Buffer(geom, 0.002)        -- pré-filtre GiST
      AND (ST_Intersects(ST_LineMerge(e.geom_way), :geom)
           OR ST_Touches(ST_LineMerge(e.geom_way), :geom))
    ON CONFLICT (event_id, edge_id) DO NOTHING;
    ```
    Plafond : max 500 edges/événement, sinon erreur explicite (protection contre une ligne tracée sur tout le pays).
  - `disable_road_closed` : cascade `UPDATE event_edge_closure SET status='disabled' WHERE event_id=:id`.
  - L'overlap GiST sur la table d'origine (1 edge) est conservé comme fast-path ; la contrainte sur `event_edge_closure` couvre le cas multi.
- Modifié `routing/service.py` : le CTE `closed` devient
  ```sql
  WITH closed AS (
    SELECT DISTINCT edge_id FROM public.event_edge_closure
    WHERE status='validated' AND now() BETWEEN start_time AND end_time
  )
  ```
  (si `MULTI_EDGE_CLOSURES=off` : CTE actuel sur `events_road_closed` — rollback exact).
- Modifié `events/schemas.py` : `RoadClosedCreate` += `derive_from_geom: bool = False` ; réponses `validate`/`get` += `affected_edges: int`, `derived_edges: int[] | null`.

**Changements frontend (EventsPage — le gros changement UI de la phase)**
- Nouveau composant `frontend/src/components/MapDrawPicker.tsx` :
  - Mode « tracé » : chaque clic carte ajoute un point le long de la route fermée (cercles + `Polyline` en cours), dernier clic modifié = annuler le point, bouton **« Terminer le tracé »** (ou double-clic) → callback avec WKT `LINESTRING(lon lat, …)` ; bouton « Annuler ».
  - Coexistence avec `MapClickPicker` existant (mode point), pas de réécriture de ce dernier.
- Modifié `pages/EventsPage.tsx` :
  - Sélecteur de mode : **Point** (comportement actuel) / **Tracé** (nouveau).
  - En mode Tracé : `geometry_wkt` = ligne dessinée par l'utilisateur (au lieu du WKT de l'edge), `edge_id` = edge anchor (le premier clic ou le plus proche), `derive_from_geom: true`.
  - Affichage post-validation : « edge 12345 **+ 18 edges concernés** ».
- Modifié `types.ts` : champs additifs ci-dessus.

**Tests**
- Ligne traversant 3 edges → 3 lignes dans `event_edge_closure` ; le routing évite les 3.
- Deux fermetures validées se chevauchant sur un edge dérivé commun → 2ᵉ validation rejetée (IntegrityError → message utilisateur).
- `disable` → le tracé d'origine revient.
- Ligne > 500 edges → erreur claire.

**Risque / rollback :** `MULTI_EDGE_CLOSURES=off` (CTE d'origine) ; la table `event_edge_closure` peut être vidée sans impact.

**Effort :** M (2 j)

### 3.3 Fermetures sans date de fin

**Constat :** `end_time NOT NULL` interdit « travaux jusqu'à nouvel ordre » (obligé de mettre +1 an).

**Changements backend**
- Schema idempotent : `ALTER TABLE public.events_road_closed ALTER COLUMN end_time DROP NOT NULL;`
  - `tstzrange(start_time, NULL)` = `'[start, )'` → la contrainte d'overlap existante reste valide **sans modification**.
- Modifié `routing/service.py` (CTE), `stats/collector.py` (`_active_closures_count`), `events/service.py` (`list_road_closed` filtre `active_now`) :
  `now() >= start_time AND (end_time IS NULL OR now() <= end_time)`.
- Modifié `events/schemas.py` : `end_time` optionnel (`null` = pas de fin).

**Frontend (EventsPage)**
- Checkbox **« Pas de date de fin »** → désactive le champ `end_time` et envoie `null`.
- Tableau : colonne end affiche « — (en cours) ».

**Tests :** fermeture `end_time=null` est active ; fermeture avec fin passée inactive ; overlap avec une fenêtre ouverte rejeté.

**Effort :** S (0,5 j)

### 3.4 Snap en une seule requête (fin du N+1)

**Changements backend**
- Modifié `routing/service.py` : `compute_route` remplace la boucle Python de `nearest_graph_node_id` par une unique requête :
  ```sql
  WITH pts(lon, lat) AS (VALUES (:p0_lon,:p0_lat), (:p1_lon,:p1_lat), ...),
  per_pt AS (
    SELECT p.later_idx, c.id, c.source, c.target, c.x1, c.y1, c.x2, c.y2,
           ROW_NUMBER() OVER (PARTITION BY p.later_idx ORDER BY c.geom_way <-> p.pt) AS rk
    FROM (SELECT row_number() OVER () AS later_idx, * FROM pts) p
    CROSS JOIN LATERAL (SELECT ... FROM algeria_2po_4pgr ORDER BY geom_way <-> p.pt LIMIT 80) c
  )
  -- endpoints + ST_Distance geography + min par pt (même logique que le code actuel)
  ```
  Logique de choix d'endpoint strictement identique (KNN 80, endpoints, distance géodésique).

**Frontend :** aucun.

**Tests :** parité — 50 points aléatoires → même `node_id` que l'implémentation précédente.

**Effort :** S (0,5 j)

### 3.5 Pool de connexions & health

**Changements backend**
- Modifié `core/db.py` : `create_engine(..., pool_size=20, max_overflow=10, pool_timeout=5, pool_pre_ping=True)` (valeurs pilotées par env).
- Modifié `main.py` : `/health` += statut du pool (`checkedin`/`checkedout`).

**Frontend :** aucun. **Effort :** S (0,5 j)

### 3.6 Durcissement des tests, collector, CI

**Changements backend**
- `tests/test_route.py` : **suppression de la tolérance `in (200, 404)`** — `pytest.skip` explicite si le graphe OSM n'est pas chargé (vérification `to_regclass` + `COUNT(*)`), sinon exiger 200 + invariants (distance > 0, géo non vide).
- Nouveau test déterministe de détour (port de la logique `smoke-route` dans pytest : fermer le 1ᵉʳ edge → 2ᵉ route ≠ 1ʳᵉ et > distance).
- Modifié `stats/collector.py` :
  - `stats_edge_usage_daily` : une seule `INSERT … SELECT :day, unnest(:ids) … ON CONFLICT DO UPDATE hits = hits + 1` au lieu de l'executemany (1 round-trip quel que soit le nombre d'edges).
  - `except Exception` silencieux → `logger.exception(...)` (rollback conservé).
- Nouveau : `.github/workflows/ci.yml` — `py_compile`, `npm run build`, tests unitaires (les tests marqués `integration` tournent avec un service Postgres+PostGIS dans la CI).

**Frontend :** aucun. **Effort :** M (1 j)

**Critère d'acceptation Phase 2 :** requête en cache < 50 ms ; fermetures multi-edges et « sans fin » fonctionnelles de bout en bout (UI → routing) ; zéro assertion tolérante dans la suite.

---

## 4. Phase 3 (P2) — Finitions métier

### 4.1 Sens de la fermeture

- Schema : `events_road_closed.direction varchar(10) NOT NULL DEFAULT 'both'` (`both` | `forward` | `reverse` ; `forward` = sens source→target osm2po) ; idem colonne sur `event_edge_closure` (appliquée par edge dérivé).
- CTE routing : `forward` → `cost = -1` uniquement ; `reverse` → `reverse_cost = -1` uniquement ; `both` → les deux (comportement actuel).
- API : champ `direction` à la création (défaut `both`).
- **Frontend (EventsPage)** : select « Sens : tous / sens de l'edge / sens inverse » (visible seulement quand un edge anchor est sélectionné).
- Tests : fermeture `forward` → le routing peut emprunter l'edge en contresens ; `both` → détour.
- Effort : S (0,5 j)

### 4.2 Évitement doux (pénalité au lieu de blocage)

- Schema : `events_road_closed.mode varchar(10) NOT NULL DEFAULT 'block'` (`block` | `penalty`) + `penalty_factor numeric NOT NULL DEFAULT 5` ; propagés sur `event_edge_closure`.
- CTE routing : `penalty` → `cost × penalty_factor` au lieu de `-1`.
- `stats_route_log` += `used_penalized_edges int` (combien d'edges pénalisés ont été empruntés).
- **Frontend (EventsPage)** : mode block/penalty + slider facteur (2–20).
- Tests : graphe où seul l'edge pénalisé relie → la route passe dessus avec durée augmentée.
- Effort : S (0,5–1 j)

### 4.3 Snap directionnel + segment de raccordement

- Backend : la fonction de snap (après batch 3.4) reçoit la direction de voyage (point précédent/suivant) ; parmi les endpoints candidates à distance ≤ 2× le minimum, priorité au candidat dont le produit scalaire avec le sens de voyage est positif (évite les U-turns au départ). En cas d'égalité → plus proche (comportement actuel).
- `RouteResponse` += `snapped: [{ lon, lat, dist_m }]` (nœud de départ/arrivée + offset).
- **Frontend (RoutePage)** : connecteurs en pointillés clic → nœud snap (départ et arrivée) + libellé « départ décalé de 120 m ». La géométrie de route elle-même reste pure.
- Tests : parité de snap sur ≥ 90 % des points (les déviations attendues = cas U-turn).
- Effort : M (1 j)

### 4.4 Alembic (versionnement des schémas)

- `backend/alembic.ini`, `alembic/env.py`, `alembic/versions/0001_baseline.py` (état complet = `SCHEMA_SQL` actuel + ajouts des phases 1–3).
- `manage.py install-schema` reste comme bootstrap idempotent ; les évolutions futures passent par des migrations Alembic.
- Effort : S (0,5 j)

**Effort Phase 3 total :** M–L (2,5–3 j), à lancer après validation de la Phase 2 en usage réel.

---

## 5. Récapitulatif Frontend (par phase)

| Phase | Fichier | Changement |
|---|---|---|
| 1 | — | **Aucun** (contrat API inchangé) |
| 2 | `components/MapDrawPicker.tsx` (nouveau) | Mode tracé : clics successifs → Polyline en cours → WKT LINESTRING |
| 2 | `pages/EventsPage.tsx` | Sélecteur Point/Tracé ; checkbox « pas de date de fin » ; affichage « + N edges concernés » |
| 2 | `types.ts` | Champs additifs (`derive_from_geom`, `affected_edges`, `derived_edges`, `end_time?`) |
| 3 | `pages/EventsPage.tsx` | Select sens de fermeture ; slider pénalité + mode block/penalty |
| 3 | `pages/RoutePage.tsx` | Connecteurs pointillés clic→nœud + info « départ décalé de X m » |
| 3 | `types.ts` | `snapped[]`, `direction`, `mode`, `penalty_factor` |

Le code frontend existant (`MapClickPicker`, `AddressAutocomplete`, `DashboardPage`, `api.ts`, `utils/geo.ts`) n'est **pas modifié** hors additions dans `types.ts`.

## 6. Récapitulatif des fichiers backend touchés

| Fichier | Phase | Type |
|---|---|---|
| `app/apps/routing/service.py` | 1, 2, 3 | modifié (coût, A*, cache, CTE multi-edge, snap batch/directionnel) |
| `app/apps/routing/costs.py` | 1 | **nouveau** |
| `app/apps/routing/schemas.py` | 3 | modifié (`snapped`) |
| `app/apps/events/service.py` | 2, 3 | modifié (derive edges, end_time null, direction, mode) |
| `app/apps/events/schemas.py` | 2, 3 | modifié (champs additifs) |
| `app/core/db.py` | 2 | modifié (pool) |
| `app/core/config.py` | 1, 2 | modifié (flags) |
| `app/main.py` | 2 | modifié (health pool, headers) |
| `app/apps/stats/collector.py` | 2 | modifié (unnest, logging) |
| `manage.py` | 0, 2 | modifié (bench-route, schema idempotent) |
| `backend/.env.example` | 1, 2 | modifié (flags) |
| `tests/test_route.py`, `tests/test_*.py` | 2, 3 | modifié/nouveau |
| `.github/workflows/ci.yml` | 2 | **nouveau** |
| `backend/alembic/`, `alembic.ini` | 3 | **nouveaux** |
| `docs/benchmarks/*.json` | 0, 1 | **nouveaux** |

## 7. jalons & critères d'acceptation

| Jalon | Contenu | Acceptation | Effort | Statut |
|---|---|---|---|---|
| **M0** | Phase 0 | `make bench` reproductible, baseline commitée | S (0,5 j) | ✅ livré (bench-route + grid ; baseline mesurée en CI via artifact) |
| **M1** | Phase 1 (P0) | p95 interurbain ≤ 50 % baseline ; qualité route ≤ 2 % dégradée ; tests verts | M (2–2,5 j) | ✅ livré (COST_MODEL + A* admissible + repli ; comparaison avant/après = artifacts CI) |
| **M2** | Phase 2 (P1) | cache < 50 ms ; multi-edge E2E UI→routing ; end_time ouverte ; tests sans tolérance ; CI verte | M–L (5–6 j) | ✅ livré (route_cache invalidation exacte ; multi-edges E2E UI→routing ; end_time NULL ; tests déterministes sur grid ; CI) |
| **M3** | Phase 3 (P2) | après validation terrain de M2 | M (2,5–3 j) | ✅ livré (sens, pénalité, snap directionnel, Alembic baseline) |

Ordre d'exécution strict : M0 → M1 → M2 → M3 (chaque jalon démo-able et rollbackable indépendamment).

## 8. Risques & mitigations

| Risque | Mitigation |
|---|---|
| A* suboptimal sur cas extrêmes (fermetures lourdes) | Heuristique admissible (UTM + v_cap) ; repli automatique Dijkstra ; contrôle qualité au bench (≤ 2 %) ; flag `ROUTING_ALGO` |
| Changement de tracés dû au coût temps | Flag `COST_MODEL=distance` ; bench avant/après documenté |
| Cache périmé | Invalidation exacte par `closure_version` (trigger) + TTL 10 min de sécurité ; flag `ROUTE_CACHE` |
| Ligne tracée géante (500+ edges) | Plafond 500 edges/événement + erreur explicite |
| Contraintes GiST sur données existantes | Pattern `DO $$ ... EXCEPTION` déjà utilisé dans le repo (safe) |
| Comportement différent si `kmh` absent | Repli coût distance, tests dédiés |

## 9. Hors périmètre (volontairement exclu de cette roadmap)

- Moteurs Contraction Hierarchies / OSRM / Valhalla (revoir uniquement si > 20–50 req/s).
- Sources automatiques d'obstacles (OSM, flux institutionnels, crowdsourcing).
- Auth/JWT, Redis, rate limiting, profils vélo/piéton, turn costs, i18n de l'UI.
(Leur place : backlog P2+ de `ANALYSE.md`, à traiter dans des tickets séparés.)

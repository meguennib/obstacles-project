import json
import os
import statistics
import time
from datetime import datetime, timedelta, timezone

import typer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import schema as core_schema
from app.core.config import settings
from app.core.db import engine
from app.core.db import SessionLocal
from app.apps.routing.service import compute_route
from app.apps.routing.schemas import RouteRequest
from app.apps.events.schemas import RoadClosedCreate
from app.apps.events.service import create_road_closed, validate_road_closed, disable_road_closed

app = typer.Typer(add_completion=False)

SCHEMA_SQL = core_schema.SCHEMA_SQL

# =====================================================================
# Graph synthétique déterministe (tests / CI / bench sans données OSM)
# Grille 12x12 de nœuds autour d'Oran (0.008° de pas).
# "Highways" (kmh=100) : ligne 0, ligne 5 (horizontales) et colonnes 0, 11
# (verticales) ; le reste kmh=50.
# Coordonnées du nœud (row, col): lon = -0.640 + col*0.008, lat = 35.660 + row*0.008
# =====================================================================
TEST_GRAPH_SQL = """
DELETE FROM public.algeria_2po_4pgr;
DELETE FROM public.algeria_2po_vertex;

-- Vertices
INSERT INTO public.algeria_2po_vertex (id, node, the_geom)
SELECT n, n,
       ST_SetSRID(ST_MakePoint(-0.640 + (n % 12) * 0.008, 35.660 + (n / 12) * 0.008), 4326)
FROM generate_series(0, 143) n;

-- Edges horizontaux (n -> n+1, sauf fin de ligne)
INSERT INTO public.algeria_2po_4pgr
  (id, source, target, cost, reverse_cost, dynamic_cost, dynamic_reverse_cost,
   km, kmh, x1, y1, x2, y2, geom_way)
SELECT 1000 + n, n, n + 1, km, km, NULL, NULL, km, kmh, x1, y1, x2, y2,
       ST_SetSRID(ST_MakeLine(ST_MakePoint(x1, y1), ST_MakePoint(x2, y2)), 4326)
FROM (
  SELECT n,
         -0.640 + (n % 12) * 0.008            AS x1,
         35.660 + (n / 12) * 0.008            AS y1,
         -0.640 + ((n + 1) % 12) * 0.008      AS x2,
         35.660 + ((n + 1) / 12) * 0.008      AS y2,
         0.7254                               AS km,
         CASE WHEN (n / 12) IN (0, 5) THEN 100.0 ELSE 50.0 END AS kmh
  FROM generate_series(0, 143) n
  WHERE n % 12 <> 11
) t;

-- Edges verticaux (n -> n+12, lignes 0..10)
INSERT INTO public.algeria_2po_4pgr
  (id, source, target, cost, reverse_cost, dynamic_cost, dynamic_reverse_cost,
   km, kmh, x1, y1, x2, y2, geom_way)
SELECT 5000 + n, n, n + 12, km, km, NULL, NULL, km, kmh, x1, y1, x2, y2,
       ST_SetSRID(ST_MakeLine(ST_MakePoint(x1, y1), ST_MakePoint(x2, y2)), 4326)
FROM (
  SELECT n,
         -0.640 + (n % 12) * 0.008            AS x1,
         35.660 + (n / 12) * 0.008            AS y1,
         -0.640 + (n % 12) * 0.008            AS x2,
         35.660 + ((n + 12) / 12) * 0.008     AS y2,
         0.8906                               AS km,
         CASE WHEN (n % 12) IN (0, 11) THEN 100.0 ELSE 50.0 END AS kmh
  FROM generate_series(0, 143) n
  WHERE n < 132
) t;
"""

# Matrice de bench "production" (points réels Algérie, nécessite import OSM)
BENCH_MATRIX_OSM = [
    ("urban_alger", (3.04197, 36.7525), (3.09000, 36.73000)),
    ("urban_oran", (-0.63000, 35.70000), (-0.58000, 35.68000)),
    ("urban_constantine", (6.60000, 36.36000), (6.64000, 36.35000)),
    ("regional_alger_blida", (3.04197, 36.7525), (2.82000, 36.47000)),
    ("regional_oran_tipaza", (-0.63000, 35.70000), (-0.77000, 35.79000)),
    ("regional_bejaia_bordj", (5.07000, 36.75000), (4.90000, 36.79000)),
    ("long_oran_alger", (-0.63000, 35.70000), (3.04197, 36.7525)),
    ("long_oran_constantine", (-0.63000, 35.70000), (6.60000, 36.36000)),
]

# Matrice de bench sur le graphe synthétique (mêmes noms de colonnes: name, start, end)
BENCH_MATRIX_GRID = [
    ("grid_west_east", (-0.640, 35.660), (-0.552, 35.660)),   # ligne 0 (highway kmh=100)
    ("grid_south_north", (-0.640, 35.660), (-0.640, 35.748)),  # colonne 0 (highway)
    ("grid_diagonal", (-0.640, 35.660), (-0.552, 35.748)),
    ("grid_mixed", (-0.616, 35.692), (-0.568, 35.716)),
]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round(pct / 100.0 * (len(values) - 1)))))
    return values[k]


def _graph_edge_count(db: Session) -> int:
    return int(db.execute(text("SELECT COUNT(*) FROM public.algeria_2po_4pgr")).scalar_one() or 0)


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


@app.command("make-test-graph")
def make_test_graph(force: bool = False):
    """Génère un graphe synthétique déterministe (grille 12x12) pour tests/CI/bench.

    Refuse de vider la table si elle contient des données (ex: import OSM)
    sauf avec --force.
    """
    with engine.begin() as conn:
        count = int(conn.execute(text("SELECT COUNT(*) FROM public.algeria_2po_4pgr")).scalar_one() or 0)
        if count > 0 and not force:
            typer.echo(f"ERREUR: {count} edges déjà présents dans algeria_2po_4pgr.")
            typer.echo("Utilisez --force pour les écraser (ATTENTION: détruit un import OSM).")
            raise typer.Exit(1)
        conn.execute(text(TEST_GRAPH_SQL))
        n_edges = int(conn.execute(text("SELECT COUNT(*) FROM public.algeria_2po_4pgr")).scalar_one())
        n_vertices = int(conn.execute(text("SELECT COUNT(*) FROM public.algeria_2po_vertex")).scalar_one())
    typer.echo(f"OK test graph: {n_vertices} vertices, {n_edges} edges (grille 12x12 autour d'Oran).")


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

    Si le graphe est le grid synthétique (< 10000 edges), les coordonnées par
    défaut sont remplacées par les coins de la grille (les points d'Alger sont
    hors du grid).
    """
    n_edges = _graph_edge_count(Session(engine))
    # Seulement si on n'a pas passé de coordonnées explicites (défauts = Alger)
    if n_edges < 10000 and n_edges > 0 and (start_lon, start_lat) == (3.04197, 36.7525):
        # Grille 12x12: nœud (row,col) -> lon=-0.640+col*0.008, lat=35.660+row*0.008
        start_lon, start_lat = -0.640, 35.660
        end_lon, end_lat = -0.552, 35.748
        via_lon, via_lat = -0.600, 35.700

    with Session(engine) as db:
        # [1] sans vias
        r1 = compute_route(db, RouteRequest(
            start={"lon": start_lon, "lat": start_lat},
            end={"lon": end_lon, "lat": end_lat},
            vias=[]
        ))
        typer.echo(f"[1] no-via: km={r1.distance_km} min={r1.duration_min} edges={len(r1.edges)} algo={r1.algo} cache_hits={r1.cache_hits}")

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
        typer.echo(f"[3] closure validated: id={ev2['id']} edge_id={ev2.get('edge_id')} affected_edges={ev2.get('affected_edges')}")

        # retest après fermeture
        try:
            r3 = compute_route(db, RouteRequest(
                start={"lon": start_lon, "lat": start_lat},
                end={"lon": end_lon, "lat": end_lat},
                vias=[]
            ))
            changed = (r3.edges[:10] != r1.edges[:10])
            typer.echo(f"[3] after-closure: km={r3.distance_km} changed={changed} cache_hits={r3.cache_hits}")
        except Exception as e:
            typer.echo(f"[3] after-closure: route failed as expected: {e}")

        # Nettoyage: on désactive la fermeture créée (pas de résidu actif)
        try:
            disable_road_closed(db, ev["id"])
            typer.echo(f"[4] cleanup: closure {ev['id']} disabled")
        except Exception as e:  # noqa: BLE001
            typer.echo(f"[4] cleanup failed: {e}")


@app.command("bench-route")
def bench_route(
    runs: int = 20,
    closures: int = 5,
    no_closures: bool = False,
    save: str = "",
):
    """Bench de routing: matrice de trajets fixes, p50/p95/moyenne.

    Mesure le calcul de route (service-level) avec le cache DÉSACTIVÉ pour
    isoler l'algorithme. Deux passes par trajet: sans fermetures, puis avec
    N fermetures validées créées le long du tracé (purgées à la fin).

    --save CHEMIN: écrit aussi le résultat en JSON (ex: docs/benchmarks/...).
    """
    db = SessionLocal()
    try:
        n_edges = _graph_edge_count(db)
        if n_edges == 0:
            typer.echo("ERREUR: graphe vide. Importez OSM ou lancez `manage.py make-test-graph`.")
            raise typer.Exit(1)

        matrix = BENCH_MATRIX_GRID if n_edges < 10000 else BENCH_MATRIX_OSM
        matrix_name = "grid" if n_edges < 10000 else "osm"
        typer.echo(f"Bench: graph={matrix_name} ({n_edges} edges), runs={runs}, closures={0 if no_closures else closures}")
        typer.echo(f"Config: cost_model={settings.cost_model} routing_algo={settings.routing_algo} (cache désactivé pour la mesure)")

        # Isoler l'algorithme: cache off pendant le bench
        cache_backup = settings.route_cache
        settings.route_cache = False

        results = []
        try:
            for name, (s_lon, s_lat), (e_lon, e_lat) in matrix:
                req = RouteRequest(
                    start={"lon": s_lon, "lat": s_lat},
                    end={"lon": e_lon, "lat": e_lat},
                    vias=[]
                )

                # --- Passe 1: sans fermetures ---
                times_ms: list[float] = []
                sample = None
                errors = 0
                for _ in range(runs):
                    t0 = time.perf_counter()
                    try:
                        sample = compute_route(db, req)
                    except Exception:
                        errors += 1
                        break
                    times_ms.append((time.perf_counter() - t0) * 1000.0)
                results.append({
                    "name": name, "mode": "no_closures", "n": len(times_ms), "errors": errors,
                    "mean_ms": round(statistics.fmean(times_ms), 2) if times_ms else None,
                    "p50_ms": round(_percentile(times_ms, 50), 2) if times_ms else None,
                    "p95_ms": round(_percentile(times_ms, 95), 2) if times_ms else None,
                    "distance_km": sample.distance_km if sample else None,
                    "duration_min": sample.duration_min if sample else None,
                    "edges": len(sample.edges) if sample else None,
                    "algo": sample.algo if sample else None,
                })
                typer.echo(f"  {name:28s} no-closures  n={len(times_ms):3d} p50={results[-1]['p50_ms']}ms p95={results[-1]['p95_ms']}ms"
                           + (f"  (erreurs: {errors})" if errors else ""))

                if no_closures or sample is None or not sample.edges:
                    continue

                # --- Passe 2: avec fermetures validées sur les N premiers edges distincts ---
                closure_ids: list[int] = []
                distinct_edges = list(dict.fromkeys(sample.edges))[:closures]
                now = datetime.now(timezone.utc)
                try:
                    for i, eid in enumerate(distinct_edges):
                        wkt = db.execute(text(
                            "SELECT ST_AsText(ST_LineMerge(geom_way)) FROM public.algeria_2po_4pgr WHERE id = :id"
                        ), {"id": eid}).scalar_one()
                        row = db.execute(text("""
                          INSERT INTO public.events_road_closed
                            (status, reason, start_time, end_time, geom, edge_id)
                          VALUES ('validated', :reason, :st, :et,
                                  ST_SetSRID(ST_GeomFromText(:wkt), 4326), :eid)
                          RETURNING id
                        """), {
                            "reason": f"bench closure {name} #{i}",
                            "st": now - timedelta(minutes=1),
                            "et": now + timedelta(hours=1),
                            "wkt": wkt,
                            "eid": eid,
                        }).scalar_one()
                        ev_id = int(row)
                        closure_ids.append(ev_id)
                        # v1.2: liage dans event_edge_closure (actif en mode MULTI_EDGE_CLOSURES)
                        db.execute(text("""
                          INSERT INTO public.event_edge_closure
                            (event_id, edge_id, start_time, end_time, status, direction, mode, penalty_factor)
                          VALUES (:ev, :eid, :st, :et, 'validated', 'both', 'block', 5)
                          ON CONFLICT (event_id, edge_id) DO NOTHING
                        """), {
                            "ev": ev_id, "eid": eid,
                            "st": now - timedelta(minutes=1),
                            "et": now + timedelta(hours=1),
                        })
                        db.commit()

                    times_ms2: list[float] = []
                    sample2 = None
                    errors2 = 0
                    for _ in range(runs):
                        t0 = time.perf_counter()
                        try:
                            sample2 = compute_route(db, req)
                        except Exception:
                            errors2 += 1
                            break
                        times_ms2.append((time.perf_counter() - t0) * 1000.0)
                    results.append({
                        "name": name, "mode": "closures", "n": len(times_ms2), "errors": errors2,
                        "mean_ms": round(statistics.fmean(times_ms2), 2) if times_ms2 else None,
                        "p50_ms": round(_percentile(times_ms2, 50), 2) if times_ms2 else None,
                        "p95_ms": round(_percentile(times_ms2, 95), 2) if times_ms2 else None,
                        "distance_km": sample2.distance_km if sample2 else None,
                        "duration_min": sample2.duration_min if sample2 else None,
                        "edges": len(sample2.edges) if sample2 else None,
                        "algo": sample2.algo if sample2 else None,
                    })
                    typer.echo(f"  {name:28s} closures={len(distinct_edges):2d} n={len(times_ms2):3d} p50={results[-1]['p50_ms']}ms p95={results[-1]['p95_ms']}ms"
                               + (f"  (erreurs: {errors2})" if errors2 else ""))
                finally:
                    if closure_ids:
                        db.execute(text("DELETE FROM public.events_road_closed WHERE id = ANY(:ids)"),
                                   {"ids": closure_ids})
                        db.commit()
        finally:
            settings.route_cache = cache_backup

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "matrix": matrix_name,
            "graph_edges": n_edges,
            "runs": runs,
            "closures": 0 if no_closures else closures,
            "route_cache": "off (mesure algorithme pur)",
            "config": {
                "cost_model": settings.cost_model,
                "routing_algo": settings.routing_algo,
                "astar_long_route_km": settings.astar_long_route_km,
                "multi_edge_closures": settings.multi_edge_closures,
            },
            "routes": results,
        }
        typer.echo("")
        typer.echo(json.dumps(report, indent=2))
        if save:
            d = os.path.dirname(save)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(save, "w") as f:
                json.dump(report, f, indent=2)
            typer.echo(f"OK bench saved: {save}")
    finally:
        db.close()


if __name__ == "__main__":
    app()

"""Validation syntaxique de TOUT le SQL généré — sans base de données.

Utilise pglast (libpg_query, parseur officiel PostgreSQL) pour détecter les
erreurs de syntaxe SQL introduites par les refactorings (CTE imbriqués,
quotes `$$ ... $$`, LATERAL, unnest WITH ORDINALITY, etc.) sans avoir besoin
d'un serveur PostGIS.

Les paramètres SQLAlchemy `:name` sont remplacés par des littéraux neutres:
la vérification est SYNTACTIQUE uniquement (les types/sémantique sont couverts
par les tests d'intégration en CI sur le grid synthétique).
"""
import re

import pytest

pglast = pytest.importorskip("pglast")

from app.apps.routing import service as svc
from app.apps.routing.costs import build_cost_expr
from app.core.config import settings
from app.core.schema import SCHEMA_SQL
from manage import TEST_GRAPH_SQL

# `:name` = paramètre SQLAlchemy — mais PAS les casts `::type` (lookbehind)
PARAM_RE = re.compile(r"(?<!:):(\w+)")

_SPECIALS = {
    "lons": "ARRAY[1.0, 2.0]",
    "lats": "ARRAY[1.0, 2.0]",
    "edge_ids": "ARRAY[1, 2]",
    "ids": "ARRAY[1, 2]",
    "wkt": "'LINESTRING(0 0, 1 1)'",
}


def _sub_params(sql: str) -> str:
    def rep(m: re.Match) -> str:
        name = m.group(1)
        if name in _SPECIALS:
            return _SPECIALS[name]
        if name in ("start_time", "end_time", "ts"):
            return "TIMESTAMPTZ '2026-01-01 00:00:00+00'"
        return "1"

    return PARAM_RE.sub(rep, sql)


def assert_parses(sql: str, label: str = "") -> None:
    try:
        parsed = pglast.parse_sql(_sub_params(sql))
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"SQL invalide [{label}]: {exc}\n--- SQL ---\n{sql}") from exc
    assert parsed, f"SQL vide [{label}]"


BB = svc.BBox(min_lon=-0.70, min_lat=35.60, max_lon=-0.50, max_lat=35.80)


def test_schema_sql_parses():
    assert_parses(SCHEMA_SQL, "SCHEMA_SQL")


def test_test_graph_sql_parses():
    assert_parses(TEST_GRAPH_SQL, "TEST_GRAPH_SQL")


@pytest.mark.parametrize("bbox", [BB, None], ids=["bbox", "full-graph"])
def test_dijkstra_sql_parses(bbox):
    assert_parses(svc.dijkstra_sql(123, 456, bbox), f"dijkstra {bbox}")


@pytest.mark.parametrize("bbox", [BB, None], ids=["bbox", "full-graph"])
def test_astar_sql_parses(bbox):
    assert_parses(svc.astar_sql(123, 456, bbox, mid_lon=-0.60, heur=0.0006), f"astar {bbox}")


def test_edges_sql_parses():
    assert_parses(svc.edges_sql_excluding_closures(BB), "edges bbox")
    assert_parses(svc.edges_sql_excluding_closures(None, with_geom=True), "edges full+geom")


def test_closed_cte_parses(monkeypatch):
    # closed_cte() est un fragment (CTE) -> on l'enveloppe pour la validation
    monkeypatch.setattr(settings, "multi_edge_closures", True)
    assert_parses(svc.closed_cte() + " SELECT 1", "closed_cte multi")
    monkeypatch.setattr(settings, "multi_edge_closures", False)
    assert_parses(svc.closed_cte() + " SELECT 1", "closed_cte legacy")


def test_snap_sql_parses():
    assert_parses(svc.snap_sql(), "snap")


def test_cache_sql_parses():
    assert_parses(svc.closure_version_sql(), "closure_version")
    assert_parses(svc.cache_get_sql(), "cache_get")
    assert_parses(svc.cache_put_sql(), "cache_put")
    assert_parses(svc.cache_cleanup_sql(), "cache_cleanup")


def test_summarize_and_penalized_sql_parses():
    assert_parses(svc.summarize_sql(), "summarize")
    assert_parses(svc.penalized_count_sql(True), "penalized multi")
    assert_parses(svc.penalized_count_sql(False), "penalized legacy")
    assert_parses(svc.route_cost_sql(), "route_cost")


@pytest.mark.parametrize("model", ["distance", "time"])
def test_cost_expr_parses(monkeypatch, model):
    # build_cost_expr() est un fragment (expression SELECT) -> on l'enveloppe
    monkeypatch.setattr(settings, "cost_model", model)
    frag = f"{build_cost_expr('cost', 'e')}, {build_cost_expr('reverse_cost', 'e')}"
    assert_parses(f"SELECT {frag} FROM public.algeria_2po_4pgr e", f"cost {model}")

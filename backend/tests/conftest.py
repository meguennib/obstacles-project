import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app as fastapi_app
from app.core.db import SessionLocal


@pytest.fixture(scope="session")
def client():
    return TestClient(fastapi_app)


@pytest.fixture(scope="session")
def graph_info():
    """Infos graphe: nombre d'edges + est-ce le graphe synthétique (grid)?"""
    try:
        with SessionLocal() as db:
            n = int(db.execute(text("SELECT COUNT(*) FROM public.algeria_2po_4pgr")).scalar_one() or 0)
    except Exception:
        n = 0
    return {"edges": n, "is_grid": 0 < n < 10000}


@pytest.fixture(scope="session")
def graph(graph_info):
    """Skip si pas de données graphe (ni OSM, ni make-test-graph)."""
    if graph_info["edges"] < 100:
        pytest.skip("No graph data in DB (run `manage.py make-test-graph` or import OSM)")
    return graph_info


@pytest.fixture()
def grid_only(graph):
    """Skip si le graphe n'est pas le grid synthétique.

    Isolation: nettoie events + fermetures multi-edges + cache avant chaque
    test -> baseline déterministe même après une exécution interrompue.
    """
    if not graph["is_grid"]:
        pytest.skip("Requires the synthetic grid (manage.py make-test-graph)")
    with SessionLocal() as db:
        db.execute(text("DELETE FROM public.event_edge_closure"))
        db.execute(text("DELETE FROM public.events_road_closed"))
        db.execute(text("DELETE FROM public.route_cache"))
        db.commit()
    return graph


def pytest_collection_modifyitems(config, items):
    # Tests d'intégration DB: exige RUN_INTEGRATION=1
    if os.getenv("RUN_INTEGRATION") != "1":
        skip = pytest.mark.skip(reason="Set RUN_INTEGRATION=1 to run DB integration tests.")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)

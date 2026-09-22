"""Modèle de coût des edges pour pgRouting (v1.2).

Deux modes (settings.cost_model):
  - "distance" : comportement d'origine — COALESCE(dynamic_cost, cost) osm2po.
  - "time"     : coût en MINUTES = km / kmh * 60 (repli distance si kmh nul).
                 L'override manuel dynamic_cost/dynamic_reverse_cost reste prioritaire.

Avec le coût "time", l'objectif de Dijkstra/A* est le trajet le plus rapide,
et la durée affichée (summarize_route) est cohérente avec l'objectif de recherche.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.apps.routing.constants import EDGES_TABLE
from app.core.config import settings

# Cache in-process de v_cap (vitesse max du graphe, km/h) — sert à l'heuristique A*.
_v_cap_lock = threading.Lock()
_v_cap: Optional[float] = None
_v_cap_ts: float = 0.0
V_CAP_TTL_SEC = 300.0


def time_cost_expr(alias: str = "e") -> str:
    """Coût temps (minutes) d'un edge; repli sur la distance si kmh nul."""
    return (
        f"CASE WHEN {alias}.kmh > 0 "
        f"THEN {alias}.km / {alias}.kmh * 60.0 "
        f"ELSE {alias}.km END"
    )


def build_cost_expr(direction: str, alias: str = "e", cost_model: Optional[str] = None) -> str:
    """Expression SQL du coût d'un edge (sens 'cost' ou 'reverse_cost').

    Mode "distance" : restitution EXACTE des expressions d'origine du projet.
    """
    cost_model = cost_model or settings.cost_model
    if cost_model == "distance":
        if direction == "cost":
            return f"COALESCE({alias}.dynamic_cost, {alias}.cost)"
        return (
            f"COALESCE({alias}.dynamic_reverse_cost, {alias}.reverse_cost, "
            f"{alias}.dynamic_cost, {alias}.cost)"
        )
    time_e = time_cost_expr(alias)
    if direction == "cost":
        return f"COALESCE({alias}.dynamic_cost, {time_e})"
    return f"COALESCE({alias}.dynamic_reverse_cost, {alias}.dynamic_cost, {time_e})"


def get_v_cap(db: Session) -> Optional[float]:
    """Vitesse maximale du graphe (km/h), mise en cache (TTL 5 min).

    Utilisée pour rendre l'heuristique A* admissible:
    temps_réel(n->cible) >= distance(n->cible) / v_cap.
    """
    global _v_cap, _v_cap_ts
    now = time.monotonic()
    with _v_cap_lock:
        if _v_cap is not None and now - _v_cap_ts < V_CAP_TTL_SEC:
            return _v_cap
    row = db.execute(text(
        f"SELECT MAX(kmh) FROM {EDGES_TABLE} WHERE kmh IS NOT NULL AND kmh > 0"
    )).scalar()
    val = float(row) if row is not None else None
    with _v_cap_lock:
        _v_cap = val
        _v_cap_ts = now
    return val


def reset_v_cap_cache() -> None:
    """Test/dev: force la recalcul du v_cap."""
    global _v_cap, _v_cap_ts
    with _v_cap_lock:
        _v_cap = None
        _v_cap_ts = 0.0

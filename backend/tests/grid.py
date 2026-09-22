"""Coordonnées du graphe synthétique déterministe (voir manage.py make-test-graph).

Grille 12x12 de nœuds autour d'Oran:
  nœud (row, col): lon = -0.640 + col*0.008, lat = 35.660 + row*0.008  (row/col 0..11)
  edge horizontal (row,col)->(row,col+1): id = 1000 + row*12 + col     (col 0..10)
  edge vertical   (row,col)->(row+1,col): id = 5000 + row*12 + col     (row 0..10)
Highways (kmh=100): lignes 0 et 5 (horizontales), colonnes 0 et 11 (verticales).
"""

LON0 = -0.640
LAT0 = 35.660
STEP = 0.008
N = 12


def node_lon(col: int) -> float:
    return LON0 + col * STEP


def node_lat(row: int) -> float:
    return LAT0 + row * STEP


def node(row: int, col: int) -> dict:
    return {"lon": node_lon(col), "lat": node_lat(row)}


def h_edge(row: int, col: int) -> int:
    """Edge horizontal (row,col) -> (row,col+1)."""
    return 1000 + row * N + col


def v_edge(row: int, col: int) -> int:
    """Edge vertical (row,col) -> (row+1,col)."""
    return 5000 + row * N + col

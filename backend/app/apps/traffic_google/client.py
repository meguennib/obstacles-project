from __future__ import annotations

import httpx

GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def compute_google_route_compare(
    api_key: str,
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
) -> tuple[float, float]:
    """
    Google Routes API (Traffic aware). Returns (distance_km, duration_min).
    On ne récupère PAS la géométrie (pas de polyline) => usage comparaison uniquement.
    """
    if not api_key:
        raise ValueError("GOOGLE_ROUTES_API_KEY not configured")

    headers = {
        "X-Goog-Api-Key": api_key,
        # On limite strictement les champs pour réduire coût/latence:
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration",
        "Content-Type": "application/json",
    }

    body = {
        "origin": {"location": {"latLng": {"latitude": start_lat, "longitude": start_lon}}},
        "destination": {"location": {"latLng": {"latitude": end_lat, "longitude": end_lon}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }

    with httpx.Client(timeout=10.0) as client:
        r = client.post(GOOGLE_ROUTES_URL, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()

    routes = data.get("routes") or []
    if not routes:
        raise ValueError("Google compare: no routes returned")

    first = routes[0]
    dist_m = float(first.get("distanceMeters") or 0.0)

    dur = first.get("duration") or "0s"  # ex: "123s"
    sec = 0.0
    if isinstance(dur, str) and dur.endswith("s"):
        try:
            sec = float(dur[:-1] or 0.0)
        except Exception:
            sec = 0.0

    distance_km = dist_m / 1000.0
    duration_min = sec / 60.0
    return distance_km, duration_min

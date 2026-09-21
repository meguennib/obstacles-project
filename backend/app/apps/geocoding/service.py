import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .schemas import GeocodeItem

# Algeria bounding rectangle (West, North, East, South) -> we use minLon,minLat,maxLon,maxLat for Photon bbox.
# West=-8.67, North=37.09, East=11.98, South=18.96 :contentReference[oaicite:3]{index=3}
DZ_MIN_LON = -8.67
DZ_MIN_LAT = 18.96
DZ_MAX_LON = 11.98
DZ_MAX_LAT = 37.09

PROVIDER = os.getenv("GEOCODER_PROVIDER", "photon").lower().strip()
BASE_URL = os.getenv("GEOCODER_BASE_URL", "https://photon.komoot.io").rstrip("/")
USER_AGENT = os.getenv("GEOCODER_USER_AGENT", "MyProject/1.0 (contact: unknown)")
MIN_INTERVAL = float(os.getenv("GEOCODER_MIN_INTERVAL_SEC", "0.3"))

CACHE_TTL_DAYS = int(os.getenv("GEOCODER_CACHE_TTL_DAYS", "30"))
CACHE_TTL_SEC = max(60, CACHE_TTL_DAYS * 24 * 3600)

_last_call_ts = 0.0
_cache: Dict[str, Tuple[float, Any]] = {}


def _cache_get(key: str) -> Optional[Any]:
    now = time.time()
    v = _cache.get(key)
    if not v:
        return None
    exp, payload = v
    if exp <= now:
        _cache.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: Any) -> None:
    _cache[key] = (time.time() + CACHE_TTL_SEC, payload)


def _throttle() -> None:
    global _last_call_ts
    now = time.time()
    dt = now - _last_call_ts
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _last_call_ts = time.time()


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _photon_label(props: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    # Commune/Wilaya mapping for DZ:
    # - wilaya ~ "state"
    # - commune ~ "city" or "district"/"locality"
    wilaya = props.get("state") or props.get("county")
    commune = props.get("city") or props.get("district") or props.get("locality") or props.get("county")

    name = props.get("name")
    housenumber = props.get("housenumber")
    street = props.get("street")

    if housenumber and street:
        primary = f"{housenumber} {street}"
        if name and name.lower() not in primary.lower():
            primary = f"{name}, {primary}"
    elif street:
        primary = f"{name}, {street}" if name and name.lower() not in street.lower() else (name or street)
    else:
        primary = name or "Sans nom"

    parts = _dedupe_keep_order([primary, commune, wilaya, "Algerie"])
    return ", ".join(parts), commune, wilaya


def photon_suggest(q: str, limit: int) -> List[GeocodeItem]:
    # bbox format: minLon,minLat,maxLon,maxLat :contentReference[oaicite:4]{index=4}
    params = {
        "q": q,
        "limit": str(max(1, min(20, limit))),
        "lang": "fr",
        "bbox": f"{DZ_MIN_LON},{DZ_MIN_LAT},{DZ_MAX_LON},{DZ_MAX_LAT}",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Language": "fr"}

    _throttle()
    with httpx.Client(timeout=12.0, headers=headers) as client:
        r = client.get(f"{BASE_URL}/api", params=params)
        r.raise_for_status()
        data = r.json()

    items: List[GeocodeItem] = []
    for feat in data.get("features", []) or []:
        props = feat.get("properties") or {}
        cc = (props.get("countrycode") or "").upper()

        # Hard gate DZ
        if cc and cc != "DZ":
            continue

        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue

        lon, lat = float(coords[0]), float(coords[1])

        label, commune, wilaya = _photon_label(props)

        items.append(
            GeocodeItem(
                label=label,
                lon=lon,
                lat=lat,
                commune=commune,
                wilaya=wilaya,
            )
        )

    return items


def photon_reverse(lon: float, lat: float) -> Optional[GeocodeItem]:
    params = {
        "lon": str(lon),
        "lat": str(lat),
        "lang": "fr",
        "limit": "1",
        "bbox": f"{DZ_MIN_LON},{DZ_MIN_LAT},{DZ_MAX_LON},{DZ_MAX_LAT}",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Language": "fr"}

    _throttle()
    with httpx.Client(timeout=12.0, headers=headers) as client:
        r = client.get(f"{BASE_URL}/reverse", params=params)
        r.raise_for_status()
        data = r.json()

    feats = data.get("features", []) or []
    if not feats:
        return None

    feat = feats[0]
    props = feat.get("properties") or {}
    cc = (props.get("countrycode") or "").upper()
    if cc and cc != "DZ":
        return None

    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates")
    if not coords or len(coords) < 2:
        return None

    lon2, lat2 = float(coords[0]), float(coords[1])
    label, commune, wilaya = _photon_label(props)

    return GeocodeItem(label=label, lon=lon2, lat=lat2, commune=commune, wilaya=wilaya)


def suggest(q: str, limit: int = 8) -> List[GeocodeItem]:
    q = (q or "").strip()
    if len(q) < 3:
        return []

    key = f"{PROVIDER}:suggest:{q.lower()}:{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if PROVIDER != "photon":
        raise RuntimeError("Only photon provider is enabled (set GEOCODER_PROVIDER=photon).")

    items = photon_suggest(q=q, limit=limit)
    _cache_set(key, items)
    return items


def reverse(lon: float, lat: float) -> Optional[GeocodeItem]:
    key = f"{PROVIDER}:reverse:{lon:.6f}:{lat:.6f}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if PROVIDER != "photon":
        raise RuntimeError("Only photon provider is enabled (set GEOCODER_PROVIDER=photon).")

    item = photon_reverse(lon=lon, lat=lat)
    _cache_set(key, item)
    return item

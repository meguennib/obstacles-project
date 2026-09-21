import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, Marker, Polyline, useMapEvents } from "react-leaflet";
import L, { Map as LeafletMap } from "leaflet";
import "leaflet/dist/leaflet.css";

import type {
    LatLng,
    RouteRequest,
    RouteResponse,
    GeocodeSuggestItem,
    GeocodeSuggestResponse,
} from "../types";
import { apiGet, apiPost } from "../api";

// Fix default marker icons (Vite)
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: new URL("leaflet/dist/images/marker-icon-2x.png", import.meta.url).toString(),
    iconUrl: new URL("leaflet/dist/images/marker-icon.png", import.meta.url).toString(),
    shadowUrl: new URL("leaflet/dist/images/marker-shadow.png", import.meta.url).toString(),
});

type PickMode = "none" | "start" | "end" | "via";

function geojsonToLatLngs(geojsonText: string): Array<Array<[number, number]>> {
    // returns list of polylines, each polyline is array of [lat,lng]
    try {
        const gj = JSON.parse(geojsonText);
        if (!gj || !gj.type) return [];

        if (gj.type === "LineString") {
            const coords: [number, number][] = gj.coordinates;
            return [coords.map(([lon, lat]) => [lat, lon])];
        }
        if (gj.type === "MultiLineString") {
            const lines: [number, number][][] = gj.coordinates;
            return lines.map((line) => line.map(([lon, lat]) => [lat, lon]));
        }
        // fallback
        return [];
    } catch {
        return [];
    }
}

function MapClickPicker({
    mode,
    onPick,
}: {
    mode: PickMode;
    onPick: (p: LatLng) => void;
}) {
    useMapEvents({
        click(e) {
            if (mode === "none") return;
            onPick({ lon: e.latlng.lng, lat: e.latlng.lat });
        },
    });
    return null;
}

function formatCoord(p: LatLng | null) {
    if (!p) return "—";
    return `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}`;
}

function fmt(n: number | null | undefined, digits = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toFixed(digits);
}

export default function RoutePage() {
    const [start, setStart] = useState<LatLng | null>(null);
    const [end, setEnd] = useState<LatLng | null>(null);
    const [vias, setVias] = useState<LatLng[]>([]);
    const [mode, setMode] = useState<PickMode>("none");

    const [compareGoogle, setCompareGoogle] = useState(false);

    const [result, setResult] = useState<RouteResponse | null>(null);
    const [err, setErr] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    const mapRef = useRef<LeafletMap | null>(null);

    // Autocomplete
    const [q, setQ] = useState("");
    const [suggestions, setSuggestions] = useState<GeocodeSuggestItem[]>([]);
    const [suggestLoading, setSuggestLoading] = useState(false);

    const polylines = useMemo(() => {
        if (!result?.geometry_geojson) return [];
        return geojsonToLatLngs(result.geometry_geojson);
    }, [result]);

    async function loadSuggest(text: string) {
        const query = text.trim();
        if (query.length < 3) {
            setSuggestions([]);
            return;
        }
        setSuggestLoading(true);
        try {
            const r = await apiGet<GeocodeSuggestResponse>(`/api/v1/geocode/suggest?q=${encodeURIComponent(query)}&limit=6`);
            setSuggestions(r.items ?? []);
        } catch {
            setSuggestions([]);
        } finally {
            setSuggestLoading(false);
        }
    }

    useEffect(() => {
        const t = setTimeout(() => loadSuggest(q), 250);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [q]);

    function applySuggestion(item: GeocodeSuggestItem, target: "start" | "end") {
        const p: LatLng = { lon: item.lon, lat: item.lat };
        if (target === "start") setStart(p);
        else setEnd(p);

        setSuggestions([]);
        setQ("");

        if (mapRef.current) {
            mapRef.current.setView([p.lat, p.lon], Math.max(mapRef.current.getZoom(), 14));
        }
    }

    function onPick(p: LatLng) {
        if (mode === "start") setStart(p);
        else if (mode === "end") setEnd(p);
        else if (mode === "via") setVias((prev) => [...prev, p]);
    }

    async function compute() {
        setErr(null);
        setResult(null);

        if (!start || !end) {
            setErr("Start et End sont requis.");
            return;
        }

        setLoading(true);
        try {
            const body: RouteRequest = { start, end, vias };

            const url = compareGoogle ? "/api/v1/route?compare=google" : "/api/v1/route";
            const r = await apiPost<RouteResponse>(url, body);
            setResult(r);

            // zoom to result
            if (mapRef.current && r.geometry_geojson) {
                const lines = geojsonToLatLngs(r.geometry_geojson);
                const latlngs: L.LatLng[] = [];
                for (const line of lines) for (const [lat, lon] of line) latlngs.push(L.latLng(lat, lon));
                if (latlngs.length > 0) {
                    const b = L.latLngBounds(latlngs);
                    mapRef.current.fitBounds(b.pad(0.15));
                }
            }
        } catch (e: any) {
            setErr(e?.message ?? "Failed to fetch");
        } finally {
            setLoading(false);
        }
    }

    function clearAll() {
        setStart(null);
        setEnd(null);
        setVias([]);
        setResult(null);
        setErr(null);
        setMode("none");
    }

    const center: [number, number] = start ? [start.lat, start.lon] : [36.753, 3.042]; // Alger default

    return (
        <div style={{ display: "flex", height: "100%" }}>
            {/* Left panel */}
            <div style={{ width: 360, borderRight: "1px solid #ddd", padding: 12, overflow: "auto" }}>
                <h2 style={{ marginTop: 0 }}>Routing</h2>

                <div style={{ display: "grid", gap: 8 }}>
                    <div style={{ display: "grid", gap: 6 }}>
                        <div style={{ fontSize: 12, color: "#666" }}>Recherche d’adresse (DZ, FR)</div>
                        <input
                            value={q}
                            onChange={(e) => setQ(e.target.value)}
                            placeholder="Ex: Place des Martyrs"
                            style={{ padding: 8, border: "1px solid #ccc", borderRadius: 8 }}
                        />
                        {suggestLoading ? <div style={{ fontSize: 12, color: "#666" }}>Recherche…</div> : null}

                        {suggestions.length > 0 && (
                            <div style={{ border: "1px solid #ddd", borderRadius: 8, background: "#fff" }}>
                                {suggestions.map((s, idx) => (
                                    <div key={idx} style={{ padding: 8, borderBottom: idx === suggestions.length - 1 ? "none" : "1px solid #eee" }}>
                                        <div style={{ fontSize: 13, fontWeight: 600 }}>{s.label}</div>
                                        <div style={{ fontSize: 12, color: "#666" }}>
                                            Commune: {s.commune ?? "—"} | Wilaya: {s.wilaya ?? "—"}
                                        </div>
                                        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                                            <button onClick={() => applySuggestion(s, "start")}>Set Start</button>
                                            <button onClick={() => applySuggestion(s, "end")}>Set End</button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <hr />

                    <div style={{ display: "grid", gap: 6 }}>
                        <div><b>Start</b>: {formatCoord(start)}</div>
                        <div><b>End</b>: {formatCoord(end)}</div>
                        <div><b>Vias</b>: {vias.length}</div>
                    </div>

                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <button onClick={() => setMode("start")} disabled={mode === "start"}>Pick Start</button>
                        <button onClick={() => setMode("end")} disabled={mode === "end"}>Pick End</button>
                        <button onClick={() => setMode("via")} disabled={mode === "via"}>Add Via</button>
                        <button onClick={() => setMode("none")} disabled={mode === "none"}>Stop Pick</button>
                    </div>

                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <input
                            id="cmpGoogle"
                            type="checkbox"
                            checked={compareGoogle}
                            onChange={(e) => setCompareGoogle(e.target.checked)}
                        />
                        <label htmlFor="cmpGoogle">Comparer Google (trafic)</label>
                    </div>

                    <div style={{ display: "flex", gap: 8 }}>
                        <button onClick={compute} disabled={loading}>
                            {loading ? "Computing…" : "Compute"}
                        </button>
                        <button onClick={() => setVias([])} disabled={vias.length === 0}>Clear vias</button>
                        <button onClick={clearAll}>Reset</button>
                    </div>

                    {err ? (
                        <div style={{ color: "crimson", background: "#fff0f0", border: "1px solid #f5c2c7", padding: 10, borderRadius: 8 }}>
                            {err}
                        </div>
                    ) : null}

                    {result ? (
                        <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 10, background: "#fff" }}>
                            <h3 style={{ marginTop: 0 }}>Résultat</h3>
                            <div>Distance: <b>{fmt(result.distance_km, 3)} km</b></div>
                            <div>Durée: <b>{fmt(result.duration_min, 1)} min</b></div>
                            <div>Edges: <b>{result.edges?.length ?? 0}</b></div>

                            {result.comparison?.google ? (
                                <>
                                    <hr />
                                    <h4 style={{ margin: "6px 0" }}>Comparaison Google (trafic)</h4>
                                    <div>Google distance: <b>{fmt(result.comparison.google.distance_km, 3)} km</b></div>
                                    <div>Google durée: <b>{fmt(result.comparison.google.duration_min, 1)} min</b></div>
                                    <div>Δ distance (nous - Google): <b>{fmt(result.comparison.google.delta_distance_km, 3)} km</b></div>
                                    <div>Δ durée (nous - Google): <b>{fmt(result.comparison.google.delta_duration_min, 1)} min</b></div>
                                </>
                            ) : compareGoogle ? (
                                <div style={{ marginTop: 8, color: "#666" }}>
                                    Comparaison Google non disponible (clé manquante ou erreur).
                                </div>
                            ) : null}
                        </div>
                    ) : null}
                </div>
            </div>

            {/* Map */}
            <div style={{ flex: 1 }}>
                <MapContainer
                    center={center}
                    zoom={12}
                    style={{ height: "100%", width: "100%" }}
                    whenReady={() => {
                        // map instance accessible via ref in "ref" in react-leaflet v4 is tricky
                    }}
                    ref={(r: any) => {
                        // react-leaflet gives Leaflet map instance in r?.leafletElement (older) or directly (newer)
                        const m = (r && (r as any).leafletElement) ? (r as any).leafletElement : r;
                        if (m && m.getCenter) mapRef.current = m as LeafletMap;
                    }}
                >
                    <TileLayer
                        attribution='&copy; OpenStreetMap contributors'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />

                    <MapClickPicker mode={mode} onPick={onPick} />

                    {start ? <Marker position={[start.lat, start.lon]} /> : null}
                    {end ? <Marker position={[end.lat, end.lon]} /> : null}
                    {vias.map((v, idx) => (
                        <Marker key={idx} position={[v.lat, v.lon]} />
                    ))}

                    {/* Route polylines */}
                    {polylines.map((line, idx) => (
                        <Polyline key={idx} positions={line.map(([lat, lon]) => [lat, lon] as [number, number])} />
                    ))}
                </MapContainer>
            </div>
        </div>
    );
}

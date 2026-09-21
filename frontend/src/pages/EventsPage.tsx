import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, Polyline } from "react-leaflet";
import type { Map as LeafletMap } from "leaflet";

import { apiGet, apiPost } from "../api";
import type { RoadClosedEvent as RoadClosed, RoadClosedEventCreate as RoadClosedCreate, NearestEdgeResponse } from "../types";
import { geojsonToPolylines } from "../utils/geo";
import MapClickPicker from "../components/MapClickPicker";

type SuggestItem = {
    label: string;
    lon: number;
    lat: number;
    commune?: string | null;
    wilaya?: string | null;
};

function secondLine(it: SuggestItem) {
    const parts = [it.commune, it.wilaya].filter((x) => !!x) as string[];
    return parts.length ? parts.join(" — ") : "Algérie";
}

function mainLine(it: SuggestItem) {
    const p = (it.label || "").split(",")[0]?.trim();
    return p && p.length > 0 ? p : it.label;
}

function AutocompleteInput({
    label,
    placeholder,
    onSelect,
}: {
    label: string;
    placeholder?: string;
    onSelect: (it: SuggestItem) => void;
}) {
    const [q, setQ] = useState("");
    const [items, setItems] = useState<SuggestItem[]>([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const timer = useRef<number | null>(null);

    async function runSuggest(query: string) {
        const qq = query.trim();
        if (qq.length < 3) {
            setItems([]);
            setOpen(false);
            return;
        }
        setLoading(true);
        try {
            const r = await apiGet<{ items: SuggestItem[] }>(
                `/api/v1/geocode/suggest?q=${encodeURIComponent(qq)}&limit=8`
            );
            setItems(r.items ?? []);
            setOpen(true);
        } catch {
            setItems([]);
            setOpen(false);
        } finally {
            setLoading(false);
        }
    }

    return (
        <div style={{ position: "relative" }}>
            <label style={{ display: "block", fontSize: 12, color: "#444" }}>{label}</label>
            <input
                value={q}
                onChange={(e) => {
                    const v = e.target.value;
                    setQ(v);
                    if (timer.current) window.clearTimeout(timer.current);
                    timer.current = window.setTimeout(() => runSuggest(v), 250);
                }}
                placeholder={placeholder ?? "Adresse (Algérie)…"}
                style={{ width: "100%", padding: 8 }}
                onFocus={() => items.length && setOpen(true)}
                onBlur={() => setTimeout(() => setOpen(false), 150)}
            />

            {loading && <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>Recherche…</div>}

            {open && items.length > 0 && (
                <div
                    style={{
                        position: "absolute",
                        zIndex: 3000,
                        left: 0,
                        right: 0,
                        marginTop: 4,
                        background: "#fff",
                        border: "1px solid #ddd",
                        maxHeight: 240,
                        overflow: "auto",
                        boxShadow: "0 6px 18px rgba(0,0,0,0.10)",
                    }}
                >
                    {items.map((it, idx) => (
                        <div
                            key={idx}
                            style={{ padding: 10, cursor: "pointer", borderBottom: "1px solid #f0f0f0" }}
                            onMouseDown={(e) => {
                                e.preventDefault();
                                onSelect(it);
                                setQ(it.label);
                                setOpen(false);
                            }}
                            title={it.label}
                        >
                            <div style={{ fontSize: 13, fontWeight: 600 }}>{mainLine(it)}</div>
                            <div style={{ fontSize: 12, color: "#666" }}>{secondLine(it)}</div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

const DEFAULT_CENTER: [number, number] = [36.7525, 3.04197];

export default function EventsPage() {
    const mapRef = useRef<LeafletMap | null>(null);

    const [items, setItems] = useState<RoadClosed[]>([]);
    const [status, setStatus] = useState<string>("validated");
    const [activeNow, setActiveNow] = useState<boolean>(true);

    const [selected, setSelected] = useState<NearestEdgeResponse | null>(null);

    const [reason, setReason] = useState<string>("closure");
    const [startTime, setStartTime] = useState<string>(new Date().toISOString());
    const [endTime, setEndTime] = useState<string>(new Date(Date.now() + 24 * 3600 * 1000).toISOString());

    const [err, setErr] = useState<string | null>(null);
    const [picking, setPicking] = useState(false);
    const [saving, setSaving] = useState(false);

    const selectedLines = useMemo(() => geojsonToPolylines(selected?.geometry_geojson), [selected]);
    const selectionOk = !!selected?.accepted;

    function getZoomSafe(): number {
        const z = mapRef.current?.getZoom();
        return typeof z === "number" ? z : 12;
    }

    function panTo(lat: number, lon: number, zoom?: number) {
        const m = mapRef.current;
        if (!m) return;
        m.setView([lat, lon], zoom ?? Math.max(m.getZoom(), 14));
    }

    async function refresh() {
        setErr(null);
        const qs = new URLSearchParams();
        if (status) qs.set("status", status);
        qs.set("active_now", String(activeNow));

        try {
            const data = await apiGet<RoadClosed[]>(`/api/v1/events/road_closed?${qs.toString()}`);
            setItems(data);
        } catch (e: any) {
            setErr(e.message ?? "Erreur list events");
        }
    }

    async function pickEdge(lat: number, lon: number, zoom: number) {
        setErr(null);
        setPicking(true);
        try {
            const r = await apiPost<NearestEdgeResponse>("/api/v1/edges/nearest", { lat, lon, zoom });
            setSelected(r);

            if (!r.accepted) {
                setErr(
                    `Clique trop loin: ${Math.round(r.distance_m)}m > seuil ${Math.round(r.threshold_m)}m (zoom ${r.zoom}). ` +
                    `👉 Zoome et clique plus près d'un axe.`
                );
            }
        } catch (e: any) {
            setErr(e.message ?? "Erreur nearest edge");
        } finally {
            setPicking(false);
        }
    }

    async function createAndValidate() {
        setErr(null);

        if (!selected) {
            setErr("Sélectionne un edge (adresse ou clic carte).");
            return;
        }
        if (!selected.accepted) {
            setErr(`Sélection non valide: ${Math.round(selected.distance_m)}m > ${Math.round(selected.threshold_m)}m.`);
            return;
        }
        if (!selected.geometry_wkt) {
            setErr("Edge sélectionné sans geometry_wkt (API).");
            return;
        }

        setSaving(true);
        try {
            const payload: RoadClosedCreate = {
                reason,
                start_time: startTime,
                end_time: endTime,
                geometry_wkt: selected.geometry_wkt,
                edge_id: selected.edge_id,
            };

            const created = await apiPost<RoadClosed>("/api/v1/events/road_closed", payload);
            await apiPost<RoadClosed>(`/api/v1/events/road_closed/${created.id}/validate`, {});
            await refresh();
        } catch (e: any) {
            setErr(e.message ?? "Erreur create/validate");
        } finally {
            setSaving(false);
        }
    }

    async function disable(id: number) {
        setErr(null);
        setSaving(true);
        try {
            await apiPost<RoadClosed>(`/api/v1/events/road_closed/${id}/disable`, {});
            await refresh();
        } catch (e: any) {
            setErr(e.message ?? "Erreur disable");
        } finally {
            setSaving(false);
        }
    }

    useEffect(() => {
        refresh();
    }, []);

    return (
        <div style={{ height: "100%", display: "grid", gridTemplateColumns: "560px 1fr" }}>
            <div style={{ borderRight: "1px solid #ddd", display: "flex", flexDirection: "column", minHeight: 0 }}>
                <div style={{ padding: 12, borderBottom: "1px solid #ddd" }}>
                    <h3 style={{ margin: 0 }}>Events — sélection par adresse OU clic carte</h3>
                    <div style={{ fontSize: 13, color: "#555" }}>
                        Adresse prioritaire : tu cherches une adresse (Algérie) puis on sélectionne l’edge le plus proche.
                    </div>

                    <div style={{ marginTop: 10 }}>
                        <AutocompleteInput
                            label="Chercher une adresse (DZ)"
                            placeholder="Ex: Place des Martyrs, Alger"
                            onSelect={(it) => {
                                const zoom = getZoomSafe();
                                panTo(it.lat, it.lon, 15);
                                pickEdge(it.lat, it.lon, zoom);
                            }}
                        />
                    </div>

                    {selected && (
                        <div style={{ marginTop: 10, fontSize: 13 }}>
                            <b>edge_id:</b> {selected.edge_id}{" "}
                            <span style={{ color: selected.accepted ? "green" : "crimson" }}>
                                {selected.accepted ? "OK" : "TROP LOIN"}
                            </span>
                            {" — "}
                            <span style={{ color: "#555" }}>
                                dist={Math.round(selected.distance_m)}m, seuil={Math.round(selected.threshold_m)}m, zoom={selected.zoom}
                            </span>
                        </div>
                    )}

                    {picking && <div style={{ marginTop: 6, fontSize: 13 }}>Sélection…</div>}
                    {err && <div style={{ marginTop: 8, color: "crimson" }}>{err}</div>}
                </div>

                <div style={{ flex: 1, minHeight: 0 }}>
                    <MapContainer
                        center={DEFAULT_CENTER}
                        zoom={12}
                        style={{ height: "100%", width: "100%" }}
                        ref={(m) => {
                            if (m) mapRef.current = m;
                        }}
                    >
                        <TileLayer
                            attribution="&copy; OpenStreetMap contributors"
                            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        />
                        <MapClickPicker
                            onPick={(lat: number, lon: number, zoom: number) => {
                                pickEdge(lat, lon, zoom);
                            }}
                        />
                        {selectedLines.map((line, i) => (
                            <Polyline key={i} positions={line} />
                        ))}
                    </MapContainer>
                </div>

                <div style={{ padding: 12, borderTop: "1px solid #ddd" }}>
                    <div style={{ display: "grid", gap: 8 }}>
                        <label>
                            reason
                            <input value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: "100%", padding: 8 }} />
                        </label>
                        <label>
                            start_time (ISO)
                            <input value={startTime} onChange={(e) => setStartTime(e.target.value)} style={{ width: "100%", padding: 8 }} />
                        </label>
                        <label>
                            end_time (ISO)
                            <input value={endTime} onChange={(e) => setEndTime(e.target.value)} style={{ width: "100%", padding: 8 }} />
                        </label>

                        <button onClick={createAndValidate} disabled={!selectionOk || saving}>
                            {saving ? "Enregistrement…" : "Create + Validate"}
                        </button>

                        {!selectionOk && (
                            <div style={{ fontSize: 12, color: "#666" }}>
                                Le bouton s’active seulement si accepted=true (edge suffisamment proche).
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <div style={{ padding: 12, minHeight: 0, overflow: "auto" }}>
                <h3>Listing</h3>

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <label>
                        Status:
                        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ marginLeft: 8 }}>
                            <option value="">(all)</option>
                            <option value="draft">draft</option>
                            <option value="validated">validated</option>
                            <option value="disabled">disabled</option>
                        </select>
                    </label>

                    <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        Active now:
                        <input type="checkbox" checked={activeNow} onChange={(e) => setActiveNow(e.target.checked)} />
                    </label>

                    <button onClick={refresh} disabled={saving}>
                        Refresh
                    </button>
                </div>

                <div style={{ marginTop: 12 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                            <tr>
                                <th style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>id</th>
                                <th style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>status</th>
                                <th style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>edge_id</th>
                                <th style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>start</th>
                                <th style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>end</th>
                                <th style={{ borderBottom: "1px solid #ddd" }}></th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((it) => (
                                <tr key={it.id}>
                                    <td>{it.id}</td>
                                    <td>{it.status}</td>
                                    <td>{it.edge_id ?? ""}</td>
                                    <td style={{ fontSize: 12 }}>{it.start_time}</td>
                                    <td style={{ fontSize: 12 }}>{it.end_time}</td>
                                    <td style={{ textAlign: "right" }}>
                                        <button onClick={() => disable(it.id)} disabled={it.status === "disabled" || saving}>
                                            Disable
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {items.length === 0 && (
                                <tr>
                                    <td colSpan={6} style={{ padding: 8, color: "#666" }}>
                                        No events
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

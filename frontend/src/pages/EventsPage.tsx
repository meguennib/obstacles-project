import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker } from "react-leaflet";
import type { Map as LeafletMap } from "leaflet";

import { apiGet, apiPost } from "../api";
import type { RoadClosedEvent as RoadClosed, RoadClosedEventCreate as RoadClosedCreate, NearestEdgeResponse } from "../types";
import { geojsonToPolylines } from "../utils/geo";
import MapClickPicker from "../components/MapClickPicker";
import MapDrawPicker from "../components/MapDrawPicker";

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

    // Mode point (origine) : edge le plus proche
    const [selected, setSelected] = useState<NearestEdgeResponse | null>(null);

    // v1.2: mode tracé (ligne) : fermetures multi-edges dérivées de la géométrie
    const [drawMode, setDrawMode] = useState<"point" | "line">("point");
    const [drawPoints, setDrawPoints] = useState<Array<[number, number]>>([]);
    const [anchorEdge, setAnchorEdge] = useState<NearestEdgeResponse | null>(null);

    const [reason, setReason] = useState<string>("closure");
    const [startTime, setStartTime] = useState<string>(new Date().toISOString());
    const [endTime, setEndTime] = useState<string>(new Date(Date.now() + 24 * 3600 * 1000).toISOString());
    const [noEnd, setNoEnd] = useState<boolean>(false); // v1.2: pas de date de fin

    // v1.2: sens + mode d'évitement
    const [direction, setDirection] = useState<"both" | "forward" | "reverse">("both");
    const [avoidMode, setAvoidMode] = useState<"block" | "penalty">("block");
    const [penaltyFactor, setPenaltyFactor] = useState<number>(5);

    const [err, setErr] = useState<string | null>(null);
    const [okMsg, setOkMsg] = useState<string | null>(null);
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

    function switchDrawMode(m: "point" | "line") {
        setErr(null);
        setOkMsg(null);
        setDrawMode(m);
        if (m === "line") {
            setSelected(null);
            setDrawPoints([]);
            setAnchorEdge(null);
        } else {
            setDrawPoints([]);
            setAnchorEdge(null);
        }
    }

    async function refresh() {
        setErr(null);
        const qs = new URLSearchParams();
        if (status) qs.set("status", status);
        qs.set("active_now", String(activeNow));

        try {
            const data = await apiGet<RoadClosed[]>(`/api/v1/events/road_closed?${qs.toString()}`);
            setItems(data);
        } catch (e) {
            setErr(e instanceof Error ? e.message : "Erreur list events");
        }
    }

    async function pickEdge(lat: number, lon: number, zoom: number) {
        setErr(null);
        setOkMsg(null);
        setPicking(true);
        try {
            const r = await apiPost<NearestEdgeResponse>("/api/v1/edges/nearest", { lat, lon, zoom });

            if (drawMode === "line") {
                // 1er clic du tracé: edge anchor (pour le reste: simple point)
                if (drawPoints.length === 0) setAnchorEdge(r);
                return r;
            }

            setSelected(r);
            if (!r.accepted) {
                setErr(
                    `Clique trop loin: ${Math.round(r.distance_m)}m > seuil ${Math.round(r.threshold_m)}m (zoom ${r.zoom}). ` +
                    `👉 Zoome et clique plus près d'un axe.`
                );
            }
        } catch (e) {
            setErr(e instanceof Error ? e.message : "Erreur nearest edge");
        } finally {
            setPicking(false);
        }
    }

    // --- v1.2: tracé ligne ---
    function onDrawClick(lat: number, lon: number) {
        setErr(null);
        setOkMsg(null);
        const pts: Array<[number, number]> = [...drawPoints, [lat, lon]];
        setDrawPoints(pts);
        // edge anchor au 1er point (si pas déjà choisi)
        if (pts.length === 1) {
            pickEdge(lat, lon, getZoomSafe());
        }
    }

    function undoDrawPoint() {
        setDrawPoints((p) => p.slice(0, -1));
    }

    function cancelDraw() {
        setDrawPoints([]);
        setAnchorEdge(null);
    }

    function drawWkt(): string | null {
        if (drawPoints.length < 2) return null;
        const coords = drawPoints.map(([la, lo]) => `${lo} ${la}`).join(", ");
        return `LINESTRING(${coords})`;
    }

    async function finishDraw() {
        const wkt = drawWkt();
        if (!wkt) {
            setErr("Tracé invalide: clique au moins 2 points le long de la route fermée.");
            return;
        }
        await createAndValidate({ geometryWkt: wkt, edgeId: anchorEdge?.edge_id ?? null, derive: true });
    }

    // --- Création + validation (point ou tracé) ---
    async function createAndValidate(opts?: { geometryWkt?: string; edgeId?: number | null; derive?: boolean }) {
        setErr(null);
        setOkMsg(null);

        const geometryWkt = opts?.geometryWkt ?? selected?.geometry_wkt;
        const edgeId = opts?.derive ? (opts.edgeId ?? null) : (selected?.edge_id ?? null);
        const derive = opts?.derive ?? false;

        if (!geometryWkt) {
            setErr(drawMode === "line"
                ? "Tracé invalide: clique au moins 2 points."
                : "Sélectionne un edge (adresse ou clic carte).");
            return;
        }
        if (edgeId == null) {
            setErr("Pas d'edge anchor (clique d'abord sur la carte).");
            return;
        }
        if (!derive && selected && !selected.accepted) {
            setErr(`Sélection non valide: ${Math.round(selected.distance_m)}m > ${Math.round(selected.threshold_m)}m.`);
            return;
        }

        setSaving(true);
        try {
            const payload: RoadClosedCreate = {
                reason,
                start_time: startTime,
                end_time: noEnd ? null : endTime,
                geometry_wkt: geometryWkt,
                edge_id: edgeId,
                derive_from_geom: derive,
                direction,
                mode: avoidMode,
                penalty_factor: penaltyFactor,
            };

            const created = await apiPost<RoadClosed>("/api/v1/events/road_closed", payload);
            const validated = await apiPost<RoadClosed>(`/api/v1/events/road_closed/${created.id}/validate`, {});
            setOkMsg(
                validated.affected_edges && validated.affected_edges > 1
                    ? `✅ Créé + validé — ${validated.affected_edges} edges concernés.`
                    : "✅ Créé + validé."
            );
            if (derive) {
                setDrawPoints([]);
                setAnchorEdge(null);
            } else {
                setSelected(null);
            }
            await refresh();
        } catch (e) {
            setErr(e instanceof Error ? e.message : "Erreur create/validate");
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
        } catch (e) {
            setErr(e instanceof Error ? e.message : "Erreur disable");
        } finally {
            setSaving(false);
        }
    }

    useEffect(() => {
        refresh();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const canCreatePoint = drawMode === "point" && selectionOk && !saving;
    const canCreateLine = drawMode === "line" && drawPoints.length >= 2 && anchorEdge != null && !saving;

    return (
        <div style={{ height: "100%", display: "grid", gridTemplateColumns: "560px 1fr" }}>
            <div style={{ borderRight: "1px solid #ddd", display: "flex", flexDirection: "column", minHeight: 0 }}>
                <div style={{ padding: 12, borderBottom: "1px solid #ddd" }}>
                    <h3 style={{ margin: 0 }}>Events — point ou tracé le long de la route</h3>
                    <div style={{ fontSize: 13, color: "#555" }}>
                        <b>Point</b> : edge le plus proche (seuil dynamique). <b>Tracé</b> : clique le long de la
                        route fermée → tous les edges traversés sont exclus (multi-edges).
                    </div>

                    <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                        <button
                            onClick={() => switchDrawMode("point")}
                            style={{ fontWeight: drawMode === "point" ? 700 : 400, outline: drawMode === "point" ? "2px solid #333" : "none" }}
                        >
                            🎯 Point
                        </button>
                        <button
                            onClick={() => switchDrawMode("line")}
                            style={{ fontWeight: drawMode === "line" ? 700 : 400, outline: drawMode === "line" ? "2px solid #333" : "none" }}
                        >
                            ✏️ Tracé
                        </button>
                    </div>

                    <div style={{ marginTop: 10 }}>
                        <AutocompleteInput
                            label="Chercher une adresse (DZ)"
                            placeholder="Ex: Place des Martyrs, Alger"
                            onSelect={(it) => {
                                const zoom = getZoomSafe();
                                panTo(it.lat, it.lon, 15);
                                if (drawMode === "line") {
                                    // adresse en 1er point du tracé
                                    setDrawPoints([]);
                                    setAnchorEdge(null);
                                    pickEdge(it.lat, it.lon, zoom);
                                } else {
                                    pickEdge(it.lat, it.lon, zoom);
                                }
                            }}
                        />
                    </div>

                    {drawMode === "line" && (
                        <div style={{ marginTop: 10, fontSize: 13 }}>
                            <div>
                                Tracé: <b>{drawPoints.length}</b> point(s)
                                {anchorEdge && <> — anchor edge: <b>{anchorEdge.edge_id}</b></>}
                            </div>
                            <div style={{ color: "#666", fontSize: 12 }}>
                                Clique le long de la route fermée. Double-clic ou « Terminer » pour valider.
                            </div>
                            <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                                <button onClick={finishDraw} disabled={!canCreateLine}>
                                    {saving ? "Enregistrement…" : "Terminer le tracé"}
                                </button>
                                <button onClick={undoDrawPoint} disabled={drawPoints.length === 0}>
                                    Annuler dernier point
                                </button>
                                <button onClick={cancelDraw} disabled={drawPoints.length === 0}>
                                    Tout annuler
                                </button>
                            </div>
                        </div>
                    )}

                    {drawMode === "point" && selected && (
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
                    {okMsg && !err && <div style={{ marginTop: 8, color: "green" }}>{okMsg}</div>}
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
                        {drawMode === "point" ? (
                            <MapClickPicker
                                onPick={(lat: number, lon: number, zoom: number) => {
                                    pickEdge(lat, lon, zoom);
                                }}
                            />
                        ) : (
                            <MapDrawPicker
                                enabled
                                onDrawClick={onDrawClick}
                                onMapDblClick={finishDraw}
                            />
                        )}

                        {/* Tracé en cours (mode ligne) */}
                        {drawMode === "line" && drawPoints.length >= 2 && (
                            <Polyline positions={drawPoints} pathOptions={{ color: "#e91e63", weight: 4, dashArray: "6 6" }} />
                        )}
                        {drawPoints.map(([la, lo], i) => (
                            <CircleMarker key={i} center={[la, lo]} radius={4} pathOptions={{ color: "#e91e63" }} />
                        ))}

                        {/* Edge sélectionné (mode point) */}
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
                        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <input type="checkbox" checked={noEnd} onChange={(e) => setNoEnd(e.target.checked)} />
                            Pas de date de fin (travaux jusqu'à nouvel ordre)
                        </label>
                        <label>
                            end_time (ISO)
                            <input
                                value={endTime}
                                onChange={(e) => setEndTime(e.target.value)}
                                disabled={noEnd}
                                style={{ width: "100%", padding: 8, opacity: noEnd ? 0.4 : 1 }}
                            />
                        </label>

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                            <label>
                                Sens
                                <select
                                    value={direction}
                                    onChange={(e) => setDirection(e.target.value as "both" | "forward" | "reverse")}
                                    style={{ width: "100%", padding: 8 }}
                                >
                                    <option value="both">Tous les sens</option>
                                    <option value="forward">Sens de l'edge (source→target)</option>
                                    <option value="reverse">Sens inverse</option>
                                </select>
                            </label>
                            <label>
                                Évitement
                                <select
                                    value={avoidMode}
                                    onChange={(e) => setAvoidMode(e.target.value as "block" | "penalty")}
                                    style={{ width: "100%", padding: 8 }}
                                >
                                    <option value="block">Blocage (détour forcé)</option>
                                    <option value="penalty">Pénalité (détour encouragé)</option>
                                </select>
                            </label>
                        </div>

                        {avoidMode === "penalty" && (
                            <label>
                                Facteur de pénalité: <b>{penaltyFactor}×</b>
                                <input
                                    type="range"
                                    min={2}
                                    max={20}
                                    step={1}
                                    value={penaltyFactor}
                                    onChange={(e) => setPenaltyFactor(Number(e.target.value))}
                                    style={{ width: "100%" }}
                                />
                            </label>
                        )}

                        <button
                            onClick={drawMode === "line" ? finishDraw : () => createAndValidate()}
                            disabled={drawMode === "point" ? !canCreatePoint : !canCreateLine}
                        >
                            {saving ? "Enregistrement…" : drawMode === "line" ? "Créer la fermeture du tracé" : "Create + Validate"}
                        </button>

                        {drawMode === "point" && !selectionOk && (
                            <div style={{ fontSize: 12, color: "#666" }}>
                                Le bouton s'active seulement si accepted=true (edge suffisamment proche).
                            </div>
                        )}
                        {drawMode === "line" && !canCreateLine && drawPoints.length < 2 && (
                            <div style={{ fontSize: 12, color: "#666" }}>
                                Clique au moins 2 points pour activer le bouton.
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
                                <th style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>edges</th>
                                <th style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>mode</th>
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
                                    <td>{(it.affected_edges ?? 0) > 1 ? `${it.affected_edges} (tracé)` : "—"}</td>
                                    <td>
                                        {it.mode === "penalty" ? `penalty ×${it.penalty_factor ?? 5}` : it.direction === "both" ? "block" : `block ${it.direction}`}
                                    </td>
                                    <td style={{ fontSize: 12 }}>{it.start_time}</td>
                                    <td style={{ fontSize: 12 }}>{it.end_time ?? "— (en cours)"}</td>
                                    <td style={{ textAlign: "right" }}>
                                        <button onClick={() => disable(it.id)} disabled={it.status === "disabled" || saving}>
                                            Disable
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {items.length === 0 && (
                                <tr>
                                    <td colSpan={8} style={{ padding: 8, color: "#666" }}>
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

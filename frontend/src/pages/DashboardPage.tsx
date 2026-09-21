import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api";

type StatsSummary = {
    days: number;
    routes_ok: number;
    routes_fail: number;
    avg_distance_km: number | null;
    avg_duration_min: number | null;
    with_active_closures: number;
    pct_with_active_closures: number;

    // Champs optionnels (si ton backend les expose)
    avg_google_distance_km?: number | null;
    avg_google_duration_min?: number | null;
    avg_delta_distance_km?: number | null;
    avg_delta_duration_min?: number | null;
};

type StatsPoint = {
    day: string;
    routes_ok: number;
    routes_fail: number;
};

type TimeseriesResponse = {
    days: number;
    points: StatsPoint[];
};

type TopEdge = {
    edge_id: number;
    hits: number;
};

type TopEdgesResponse = {
    days: number;
    items: TopEdge[];
};

type TopFailure = {
    error_type: string;
    error_message: string;
    hits: number;
};

type TopFailuresResponse = {
    days: number;
    items: TopFailure[];
};

function Card({
    title,
    value,
    sub,
}: {
    title: string;
    value: string;
    sub?: string;
}) {
    return (
        <div
            style={{
                border: "1px solid #ddd",
                borderRadius: 10,
                padding: 12,
                background: "#fff",
            }}
        >
            <div style={{ fontSize: 12, color: "#666" }}>{title}</div>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 4 }}>{value}</div>
            {sub ? (
                <div style={{ fontSize: 12, color: "#777", marginTop: 4 }}>{sub}</div>
            ) : null}
        </div>
    );
}

function fmt(n: number | null | undefined, digits = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toFixed(digits);
}

function fmtSigned(n: number | null | undefined, digits = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    const v = Number(n);
    const s = v > 0 ? "+" : "";
    return `${s}${v.toFixed(digits)}`;
}

export default function DashboardPage() {
    const [days, setDays] = useState<number>(30);

    const [summary, setSummary] = useState<StatsSummary | null>(null);
    const [ts, setTs] = useState<TimeseriesResponse | null>(null);
    const [topEdges, setTopEdges] = useState<TopEdgesResponse | null>(null);
    const [topFailures, setTopFailures] = useState<TopFailuresResponse | null>(null);

    const [loading, setLoading] = useState(false);
    const [err, setErr] = useState<string | null>(null);

    async function loadAll() {
        setErr(null);
        setLoading(true);
        try {
            const [s, t, e, f] = await Promise.all([
                apiGet<StatsSummary>(`/api/v1/stats/summary?days=${days}`),
                apiGet<TimeseriesResponse>(`/api/v1/stats/timeseries?days=${days}`),
                apiGet<TopEdgesResponse>(
                    `/api/v1/stats/top-edges?days=${Math.min(days, 30)}&limit=20`
                ),
                apiGet<TopFailuresResponse>(`/api/v1/stats/top-failures?days=${days}&limit=10`),
            ]);
            setSummary(s);
            setTs(t);
            setTopEdges(e);
            setTopFailures(f);
        } catch (e: any) {
            setErr(e?.message ?? "Failed to load stats");
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        loadAll();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [days]);

    const totals = useMemo(() => {
        const points = ts?.points ?? [];
        let ok = 0;
        let fail = 0;
        for (const p of points) {
            ok += p.routes_ok;
            fail += p.routes_fail;
        }
        return { ok, fail };
    }, [ts]);

    const hasGoogle =
        summary?.avg_google_duration_min !== undefined ||
        summary?.avg_google_distance_km !== undefined ||
        summary?.avg_delta_duration_min !== undefined ||
        summary?.avg_delta_distance_km !== undefined;

    return (
        <div
            style={{
                padding: 12,
                height: "100%",
                overflow: "auto",
                background: "#f7f7f7",
            }}
        >
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <h2 style={{ margin: 0 }}>Dashboard (stats internes)</h2>

                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    Période:
                    <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                        <option value={7}>7 jours</option>
                        <option value={30}>30 jours</option>
                        <option value={90}>90 jours</option>
                    </select>
                </label>

                <button onClick={loadAll} disabled={loading}>
                    {loading ? "Refresh…" : "Refresh"}
                </button>

                {err ? <span style={{ color: "crimson" }}>{err}</span> : null}
            </div>

            {/* Bloc principal */}
            <div
                style={{
                    marginTop: 12,
                    display: "grid",
                    gridTemplateColumns: "repeat(4, minmax(160px, 1fr))",
                    gap: 12,
                }}
            >
                <Card
                    title="Routes OK"
                    value={summary ? String(summary.routes_ok) : "—"}
                    sub={`sur ${summary?.days ?? days} jours`}
                />
                <Card
                    title="Routes FAIL"
                    value={summary ? String(summary.routes_fail) : "—"}
                    sub="erreurs / 400"
                />
                <Card
                    title="Distance moyenne (nous)"
                    value={summary ? `${fmt(summary.avg_distance_km, 2)} km` : "—"}
                    sub="sur routes OK"
                />
                <Card
                    title="Durée moyenne (nous)"
                    value={summary ? `${fmt(summary.avg_duration_min, 1)} min` : "—"}
                    sub="sur routes OK"
                />
            </div>

            {/* Bloc Google compare (si présent) */}
            <div style={{ marginTop: 12 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                    <h3 style={{ margin: 0 }}>Comparaison Google (trafic)</h3>
                    {!hasGoogle ? (
                        <span style={{ fontSize: 12, color: "#666" }}>
                            (active si tu fais des routes avec <code>?compare=google</code>)
                        </span>
                    ) : null}
                </div>

                <div
                    style={{
                        marginTop: 10,
                        display: "grid",
                        gridTemplateColumns: "repeat(4, minmax(160px, 1fr))",
                        gap: 12,
                    }}
                >
                    <Card
                        title="Dist. Google"
                        value={summary && summary.avg_google_distance_km != null ? `${fmt(summary.avg_google_distance_km, 2)} km` : "—"}
                    />
                    <Card
                        title="Durée Google"
                        value={summary && summary.avg_google_duration_min != null ? `${fmt(summary.avg_google_duration_min, 1)} min` : "—"}
                    />
                    <Card
                        title="Δ Distance"
                        value={summary && summary.avg_delta_distance_km != null ? `${fmtSigned(summary.avg_delta_distance_km, 2)} km` : "—"}
                        sub="Positif = nous > Google"
                    />
                    <Card
                        title="Δ Durée"
                        value={summary && summary.avg_delta_duration_min != null ? `${fmtSigned(summary.avg_delta_duration_min, 1)} min` : "—"}
                        sub="Positif = nous > Google"
                    />
                </div>
            </div>

            <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 12 }}>
                <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 12, background: "#fff" }}>
                    <h3 style={{ marginTop: 0 }}>Time series (OK/FAIL par jour)</h3>
                    <div style={{ fontSize: 13, color: "#666", marginBottom: 8 }}>
                        Total période: OK={totals.ok} / FAIL={totals.fail}
                    </div>

                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                            <tr>
                                <th style={{ textAlign: "left", borderBottom: "1px solid #eee", paddingBottom: 6 }}>Day</th>
                                <th style={{ textAlign: "right", borderBottom: "1px solid #eee", paddingBottom: 6 }}>OK</th>
                                <th style={{ textAlign: "right", borderBottom: "1px solid #eee", paddingBottom: 6 }}>FAIL</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(ts?.points ?? []).map((p) => (
                                <tr key={p.day}>
                                    <td style={{ padding: "6px 0", borderBottom: "1px solid #f3f3f3" }}>{p.day}</td>
                                    <td style={{ textAlign: "right", borderBottom: "1px solid #f3f3f3" }}>{p.routes_ok}</td>
                                    <td style={{ textAlign: "right", borderBottom: "1px solid #f3f3f3" }}>{p.routes_fail}</td>
                                </tr>
                            ))}
                            {!ts?.points?.length && (
                                <tr>
                                    <td colSpan={3} style={{ color: "#777", paddingTop: 8 }}>
                                        No data
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>

                <div style={{ display: "grid", gap: 12 }}>
                    <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 12, background: "#fff" }}>
                        <h3 style={{ marginTop: 0 }}>Closures actives</h3>
                        <div style={{ fontSize: 26, fontWeight: 700 }}>{summary ? String(summary.with_active_closures) : "—"}</div>
                        <div style={{ fontSize: 13, color: "#666" }}>
                            % routes OK affectées: {summary ? `${fmt(summary.pct_with_active_closures, 1)}%` : "—"}
                        </div>
                    </div>

                    <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 12, background: "#fff" }}>
                        <h3 style={{ marginTop: 0 }}>Top edges (hits)</h3>
                        <table style={{ width: "100%", borderCollapse: "collapse" }}>
                            <thead>
                                <tr>
                                    <th style={{ textAlign: "left", borderBottom: "1px solid #eee", paddingBottom: 6 }}>edge_id</th>
                                    <th style={{ textAlign: "right", borderBottom: "1px solid #eee", paddingBottom: 6 }}>hits</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(topEdges?.items ?? []).map((it) => (
                                    <tr key={it.edge_id}>
                                        <td style={{ padding: "6px 0", borderBottom: "1px solid #f3f3f3" }}>{it.edge_id}</td>
                                        <td style={{ textAlign: "right", borderBottom: "1px solid #f3f3f3" }}>{it.hits}</td>
                                    </tr>
                                ))}
                                {!topEdges?.items?.length && (
                                    <tr>
                                        <td colSpan={2} style={{ color: "#777", paddingTop: 8 }}>
                                            No data
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                        <div style={{ fontSize: 12, color: "#777", marginTop: 6 }}>
                            Période: {topEdges?.days ?? Math.min(days, 30)} jours
                        </div>
                    </div>

                    <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 12, background: "#fff" }}>
                        <h3 style={{ marginTop: 0 }}>Top failures</h3>
                        {(topFailures?.items ?? []).length === 0 ? (
                            <div style={{ color: "#777" }}>Aucune erreur enregistrée.</div>
                        ) : (
                            <table style={{ width: "100%", borderCollapse: "collapse" }}>
                                <thead>
                                    <tr>
                                        <th style={{ textAlign: "left", borderBottom: "1px solid #eee", paddingBottom: 6 }}>type</th>
                                        <th style={{ textAlign: "right", borderBottom: "1px solid #eee", paddingBottom: 6 }}>hits</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(topFailures?.items ?? []).map((it, idx) => (
                                        <tr key={idx}>
                                            <td style={{ padding: "6px 0", borderBottom: "1px solid #f3f3f3" }}>
                                                <div style={{ fontWeight: 600 }}>{it.error_type}</div>
                                                <div style={{ fontSize: 12, color: "#666" }}>{it.error_message}</div>
                                            </td>
                                            <td style={{ textAlign: "right", borderBottom: "1px solid #f3f3f3" }}>{it.hits}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

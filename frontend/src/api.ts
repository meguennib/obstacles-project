const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function readErrorDetail(r: Response): Promise<string> {
    const ct = r.headers.get("content-type") ?? "";
    if (ct.includes("application/json")) {
        try {
            const j = await r.json();
            return j?.detail ?? JSON.stringify(j);
        } catch {
            return `HTTP ${r.status}`;
        }
    }
    // HTML ou texte
    try {
        const t = await r.text();
        return t?.slice(0, 300) || `HTTP ${r.status}`;
    } catch {
        return `HTTP ${r.status}`;
    }
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
    const r = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
    });
    if (!r.ok) {
        throw new Error(await readErrorDetail(r));
    }
    return r.json();
}

export async function apiGet<T>(path: string): Promise<T> {
    const r = await fetch(`${API_BASE}${path}`);
    if (!r.ok) {
        throw new Error(await readErrorDetail(r));
    }
    return r.json();
}

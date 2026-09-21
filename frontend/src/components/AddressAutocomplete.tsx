import { useEffect, useRef, useState } from "react";
import { apiGet } from "../api";

type Item = { label: string; lon: number; lat: number; importance?: number | null };

export default function AddressAutocomplete({
    label,
    placeholder,
    onSelect,
}: {
    label: string;
    placeholder?: string;
    onSelect: (item: Item) => void;
}) {
    const [q, setQ] = useState("");
    const [items, setItems] = useState<Item[]>([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const t = useRef<number | null>(null);

    useEffect(() => {
        if (t.current) window.clearTimeout(t.current);
        const qq = q.trim();
        if (qq.length < 3) {
            setItems([]);
            setOpen(false);
            return;
        }
        t.current = window.setTimeout(async () => {
            setLoading(true);
            try {
                const r = await apiGet<{ items: Item[] }>(`/api/v1/geocode/suggest?q=${encodeURIComponent(qq)}&limit=8`);
                setItems(r.items ?? []);
                setOpen(true);
            } catch {
                setItems([]);
                setOpen(false);
            } finally {
                setLoading(false);
            }
        }, 250);
        return () => {
            if (t.current) window.clearTimeout(t.current);
        };
    }, [q]);

    return (
        <div style={{ position: "relative" }}>
            <label style={{ display: "block", fontSize: 12, color: "#444" }}>{label}</label>
            <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={placeholder ?? "Adresse en Algérie…"}
                style={{ width: "100%", padding: 8 }}
                onFocus={() => items.length && setOpen(true)}
                onBlur={() => setTimeout(() => setOpen(false), 150)}
            />
            {loading && <div style={{ fontSize: 12, color: "#666" }}>Recherche…</div>}
            {open && items.length > 0 && (
                <div
                    style={{
                        position: "absolute",
                        zIndex: 2000,
                        left: 0,
                        right: 0,
                        background: "#fff",
                        border: "1px solid #ddd",
                        maxHeight: 220,
                        overflow: "auto",
                    }}
                >
                    {items.map((it, idx) => (
                        <div
                            key={idx}
                            style={{ padding: 8, cursor: "pointer", borderBottom: "1px solid #f0f0f0" }}
                            onMouseDown={(e) => {
                                e.preventDefault();
                                onSelect(it);
                                setQ(it.label);
                                setOpen(false);
                            }}
                        >
                            {it.label}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

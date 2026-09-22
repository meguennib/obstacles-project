import { useEffect, useRef } from "react";
import { useMapEvents } from "react-leaflet";

/**
 * v1.2: sélecteur "tracé" — chaque clic ajoute un point le long de la route
 * fermée (utilisé par EventsPage en mode ligne). Double-clic = terminer.
 *
 * Note: Leaflet émet d'abord deux `click` avant le `dblclick` -> on retarde
 * chaque clic de 250 ms et on l'annule si le double-clic arrive (sinon le
 * double-clic de fin ajouterait 2 points parasites au tracé).
 */
const CLICK_DELAY_MS = 250;

export default function MapDrawPicker({
    enabled,
    onDrawClick,
    onMapDblClick,
}: {
    enabled: boolean;
    onDrawClick: (lat: number, lon: number) => void;
    onMapDblClick?: () => void;
}) {
    const pendingClick = useRef<number | null>(null);

    const map = useMapEvents({
        click(e) {
            if (!enabled) return;
            const lat = e.latlng.lat;
            const lon = e.latlng.lng;
            if (pendingClick.current) window.clearTimeout(pendingClick.current);
            pendingClick.current = window.setTimeout(() => {
                pendingClick.current = null;
                onDrawClick(lat, lon);
            }, CLICK_DELAY_MS);
        },
        dblclick(e) {
            if (!enabled) return;
            if (pendingClick.current) {
                window.clearTimeout(pendingClick.current);
                pendingClick.current = null;
            }
            e.originalEvent.preventDefault?.();
            onMapDblClick?.();
        },
    });

    useEffect(() => {
        if (!map) return;
        if (enabled) map.doubleClickZoom.disable();
        else map.doubleClickZoom.enable();
        return () => {
            if (pendingClick.current) {
                window.clearTimeout(pendingClick.current);
                pendingClick.current = null;
            }
        };
    }, [enabled, map]);

    return null;
}

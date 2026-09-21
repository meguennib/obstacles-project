import { useMapEvents } from "react-leaflet";

export default function MapClickPicker({
    onPick,
}: {
    onPick: (lat: number, lon: number, zoom: number) => void;
}) {
    const map = useMapEvents({
        click(e) {
            onPick(e.latlng.lat, e.latlng.lng, map.getZoom());
        },
    });
    return null;
}

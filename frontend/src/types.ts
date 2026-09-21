// --- Routing types ---
export type LatLng = { lon: number; lat: number };

export type RouteRequest = {
    start: LatLng;
    end: LatLng;
    vias: LatLng[];
    profile?: string;
};

export type GoogleCompare = {
    distance_km: number;
    duration_min: number;
    delta_distance_km: number;
    delta_duration_min: number;
};

export type RouteComparison = {
    google?: GoogleCompare | null;
};

export type RouteResponse = {
    distance_km: number;
    duration_min: number;
    edges: number[];
    geometry_geojson: string;
    comparison?: RouteComparison | null;
};

// --- Events types ---
export type RoadClosedStatus = "draft" | "validated" | "disabled";

export type RoadClosedEventCreate = {
    start_time: string;
    end_time: string;
    reason?: string;
    edge_id?: number | null;
    geometry_wkt?: string | null;
};

export type RoadClosedEvent = {
    id: number;
    status: RoadClosedStatus;
    start_time: string;
    end_time: string;
    reason?: string | null;
    edge_id?: number | null;
    geometry_wkt?: string | null;
};

// --- Nearest Edge type ---
export type NearestEdgeResponse = {
    edge_id: number;
    distance_m: number;
    threshold_m: number;
    zoom: number;
    accepted: boolean;
    geometry_wkt?: string | null;
    geometry_geojson?: string | null;
};

// --- Geocode types ---
export type GeocodeSuggestItem = {
    label: string;
    lon: number;
    lat: number;
    commune?: string | null;
    wilaya?: string | null;
};

export type GeocodeSuggestResponse = {
    items: GeocodeSuggestItem[];
};

export type ReverseGeocodeResponse = {
    label?: string | null;
    lon: number;
    lat: number;
    commune?: string | null;
    wilaya?: string | null;
};

// --- Stats types (dashboard) ---
export type StatsSummary = {
    days: number;
    routes_ok: number;
    routes_fail: number;
    avg_distance_km: number | null;
    avg_duration_min: number | null;
    with_active_closures: number;
    pct_with_active_closures: number;
};

export type StatsPoint = { day: string; routes_ok: number; routes_fail: number };
export type TimeseriesResponse = { days: number; points: StatsPoint[] };

export type TopEdge = { edge_id: number; hits: number };
export type TopEdgesResponse = { days: number; items: TopEdge[] };

export type TopFailure = { error_type: string; error_message: string; hits: number };
export type TopFailuresResponse = { days: number; items: TopFailure[] };

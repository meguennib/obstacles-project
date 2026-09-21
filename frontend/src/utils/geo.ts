export type LatLngTuple = [number, number];

export function geojsonToPolylines(geojsonStr?: string | null): LatLngTuple[][] {
    if (!geojsonStr) return [];
    const g = JSON.parse(geojsonStr);

    if (g.type === "LineString") {
        return [g.coordinates.map((c: number[]) => [c[1], c[0]] as LatLngTuple)];
    }
    if (g.type === "MultiLineString") {
        return g.coordinates.map((line: number[][]) =>
            line.map((c) => [c[1], c[0]] as LatLngTuple)
        );
    }
    return [];
}

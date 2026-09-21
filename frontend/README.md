# Frontend - Obstacles Routing (React + Leaflet)

Interface React 19 + TypeScript + Vite + Leaflet pour calcul d'itinéraires avec évitement d'obstacles.

## Pages

- **RoutePage** (`/`) : pick Start/End/Via sur carte, recherche adresse DZ (Photon), calcul route `POST /api/v1/route`, affichage polyline + distance/durée + comparaison Google (`?compare=google`), fitBounds
- **EventsPage** : création fermetures via adresse OU clic carte -> `POST /api/v1/edges/nearest` avec seuil dynamique, formulaire raison/dates, `POST /road_closed` + `validate`, liste filtrée + disable
- **DashboardPage** : stats `summary`, `timeseries`, `top-edges`, `top-failures`, cards distance/durée + Google delta

## Stack

- Vite 7.2.4 + @vitejs/plugin-react
- React 19.2 + react-dom
- Leaflet 1.9.4 + react-leaflet 5.0
- TypeScript 5.9
- ESLint

## Config

`vite.config.ts`:
- `server.host: 0.0.0.0`, `port: 5173`
- proxy `/api -> http://localhost:8000` (pour dev)
- `preview.host: 0.0.0.0`

`.env`:
```ini
VITE_API_BASE=http://localhost:8000
```

## Lancement

```bash
npm install
cp .env.example .env
npm run dev -- --host 0.0.0.0 --port 5173
# build
npm run build
npm run preview
```

## Docker

```bash
docker build --build-arg VITE_API_BASE=http://localhost:8000 -t obstacles-frontend .
docker run -p 5173:80 obstacles-frontend
# nginx.conf proxy /api/ -> backend:8000
```

## Structure

```
src/
├── App.tsx (tabs routing/events/dashboard)
├── main.tsx
├── index.css (fix * box-sizing)
├── api.ts (VITE_API_BASE, apiGet/apiPost avec error parsing)
├── types.ts (RouteRequest, RouteResponse, NearestEdgeResponse, Geocode, Stats)
├── pages/
│   ├── RoutePage.tsx
│   ├── EventsPage.tsx
│   └── DashboardPage.tsx
├── components/
│   ├── AddressAutocomplete.tsx
│   └── MapClickPicker.tsx
└── utils/geo.ts (geojsonToPolylines)
```

## API utilisée

- `GET /api/v1/geocode/suggest?q&limit`
- `POST /api/v1/edges/nearest` `{lon,lat,zoom}`
- `POST /api/v1/route` + `?compare=google`
- `GET/POST /api/v1/events/road_closed`
- `GET /api/v1/stats/*`

## Fixes v1.1.0

- Fix `index.css` invalide
- Ajout proxy Vite + host 0.0.0.0 pour Arena preview
- Ajout `.env.example`
- Ajout `nginx.conf` + `Dockerfile` multi-stage

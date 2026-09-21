import { useState } from "react";
import RoutePage from "./pages/RoutePage";
import EventsPage from "./pages/EventsPage";
import DashboardPage from "./pages/DashboardPage";

export default function App() {
  const [tab, setTab] = useState<"route" | "events" | "dashboard">("route");

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <header style={{ padding: 10, borderBottom: "1px solid #ddd", display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={() => setTab("route")} disabled={tab === "route"}>
          Routing
        </button>
        <button onClick={() => setTab("events")} disabled={tab === "events"}>
          Events
        </button>
        <button onClick={() => setTab("dashboard")} disabled={tab === "dashboard"}>
          Dashboard
        </button>
      </header>

      <div style={{ flex: 1, minHeight: 0 }}>
        {tab === "route" ? <RoutePage /> : tab === "events" ? <EventsPage /> : <DashboardPage />}
      </div>
    </div>
  );
}

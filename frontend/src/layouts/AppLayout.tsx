import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import MapView from "../components/MapView";

const PANEL_ROUTES = new Set(["/plan", "/explore", "/login", "/register"]);

export default function AppLayout() {
  const location = useLocation();
  const [panelOpen, setPanelOpen] = useState(PANEL_ROUTES.has(location.pathname));

  useEffect(() => {
    if (PANEL_ROUTES.has(location.pathname)) {
      setPanelOpen(true);
    }
  }, [location.pathname]);

  const navItems = useMemo(
    () => [
      { to: "/", label: "Map" },
      { to: "/plan", label: "Plan" },
      { to: "/explore", label: "Explore" },
      { to: "/login", label: "Login" },
    ],
    [],
  );

  return (
    <div className="app-shell" data-panel={panelOpen ? "open" : "closed"}>
      <aside className="panel-shell">
        <div className="panel-inner">
          <header className="panel-header">
            <div className="brand-mark">
              <span className="brand-title">Walkmap</span>
              <span className="brand-subtitle">Aesthetic Walk Planner</span>
            </div>
            <button
              className="panel-collapse"
              type="button"
              onClick={() => setPanelOpen((open) => !open)}
              aria-label={panelOpen ? "Collapse panel" : "Expand panel"}
            >
              {panelOpen ? "Hide" : "Show"}
            </button>
          </header>

          <nav className="panel-nav">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className="nav-link"
                data-active={location.pathname === item.to}
              >
                {item.label}
              </NavLink>
            ))}
            <NavLink
              to="/register"
              className="nav-link"
              data-active={location.pathname === "/register"}
            >
              Register
            </NavLink>
          </nav>

          <div className="panel-grid animate-floatIn">
            <Outlet />
          </div>

          <section className="panel-section">
            <p className="text-sm text-moss">
              Status: Mock data wired. Map overlay and routing engine will
              integrate once API endpoints land.
            </p>
          </section>
        </div>
      </aside>

      <section className="map-shell">
        <MapView />
        {!panelOpen && (
          <button
            className="panel-toggle"
            type="button"
            onClick={() => setPanelOpen(true)}
          >
            Open Panel
          </button>
        )}
      </section>
    </div>
  );
}

import { useMemo } from "react";
import {
  formatCoordinateLabel,
  LOCATION_PRESETS,
  measurementToMeters,
  parseLocationInput,
  type ActivityMode,
  type PriorityMode,
  type RouteMode,
  useRoutePlanner,
} from "../components/routePlanner";

const ROUTE_MODES: Array<{ value: RouteMode; label: string; blurb: string }> = [
  {
    value: "loop",
    label: "Loop",
    blurb: "Return to where you began.",
  },
  {
    value: "point-to-point",
    label: "Point to Point",
    blurb: "Travel between two anchors with a more open finish.",
  },
  {
    value: "point-to-destination",
    label: "Destination",
    blurb: "Aim for a specific endpoint.",
  },
];

const ACTIVITY_MODES: Array<{ value: ActivityMode; label: string }> = [
  { value: "walk", label: "Walk" },
  { value: "run", label: "Run" },
];

const PRIORITY_MODES: Array<{ value: PriorityMode; label: string; tone: string }> = [
  { value: "highest-rated", label: "Highest Rated", tone: "Best overall block scores" },
  { value: "dining", label: "Dining & Shopping", tone: "Livelier storefront corridors" },
  { value: "residential", label: "Residential", tone: "Calmer neighborhood stretches" },
  { value: "explore", label: "Explore", tone: "Unexpected scenic variety" },
];

const friendlyError = (message: string | undefined) => {
  if (!message) {
    return "Route suggestions are unavailable right now. Please try again.";
  }
  if (message.toLowerCase().includes("end is required")) {
    return "Add an end point for this route mode before searching.";
  }
  return message;
};

const formatMiles = (value: number) => `${value.toFixed(1)} mi`;

const formatDuration = (seconds: number) => {
  const totalMinutes = Math.max(1, Math.round(seconds / 60));
  if (totalMinutes >= 60) {
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return minutes > 0 ? `${hours} hr ${minutes} min` : `${hours} hr`;
  }
  return `${totalMinutes} min`;
};

const getApiBase = () => {
  const rawBase = import.meta.env.VITE_API_BASE_URL;
  if (!rawBase) {
    return "";
  }
  return rawBase.endsWith("/") ? rawBase.slice(0, -1) : rawBase;
};

export default function PlanPanel() {
  const {
    form,
    loading,
    error,
    setForm,
    setRoutes,
    setLoading,
    setError,
    clearRoutes,
  } = useRoutePlanner();

  const apiBase = useMemo(() => getApiBase(), []);
  const needsEndPoint = form.mode !== "loop";
  const distanceMeters = measurementToMeters(
    form.measurement,
    form.distanceMiles,
    form.durationMinutes,
    form.activity,
  );

  const onUseLocation = async () => {
    if (!navigator.geolocation) {
      setError("This browser does not support geolocation.");
      return;
    }

    setError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const next = {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        };
        setForm((current) => ({
          ...current,
          start: next,
          startLabel: `Current location · ${formatCoordinateLabel(next)}`,
        }));
      },
      () => {
        setError("We couldn’t access your location. You can still paste coordinates or choose a saved landmark.");
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
      },
    );
  };

  const submitRoutes = async () => {
    const start = form.start ?? parseLocationInput(form.startLabel);
    const end = needsEndPoint
      ? form.end ?? parseLocationInput(form.endLabel)
      : null;

    if (!start) {
      setError("Choose a starting point from the list, use your location, or paste coordinates like 40.7178, -74.0431.");
      return;
    }

    if (needsEndPoint && !end) {
      setError("Add an end point for this route mode before searching.");
      return;
    }

    setLoading(true);
    setError(null);
    clearRoutes();

    try {
      const response = await fetch(apiBase ? `${apiBase}/routes/suggest` : "/routes/suggest", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          start,
          end,
          mode: form.mode,
          distance_m: Math.round(distanceMeters),
          activity: form.activity,
          priority: form.priority,
        }),
      });

      const payload = (await response.json()) as {
        detail?: string;
        routes?: Array<{
          segment_ids: string[];
          geometry: {
            type: "LineString";
            coordinates: [number, number][];
          };
          distance_m: number;
          duration_s: number;
          avg_score: number;
          verified_count: number;
          unverified_count: number;
        }>;
      };

      if (!response.ok || !payload.routes) {
        throw new Error(friendlyError(payload.detail));
      }

      setRoutes(
        payload.routes.map((route, index) => ({
          routeId: `route-${index + 1}`,
          segmentIds: route.segment_ids,
          geometry: route.geometry,
          distanceM: route.distance_m,
          durationS: route.duration_s,
          avgScore: route.avg_score,
          verifiedCount: route.verified_count,
          unverifiedCount: route.unverified_count,
        })),
      );
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Route suggestions are unavailable right now. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <section className="panel-section">
        <p className="planner-kicker">Route Atelier</p>
        <h2 className="text-xl">Plan a Route</h2>
        <p className="mt-2 text-sm text-moss">
          Shape the walk first, then let the planner draft a few high-character
          options across the map.
        </p>
      </section>

      <section className="panel-section">
        <div className="planner-stack">
          <div className="panel-field">
            <label className="panel-label" htmlFor="start">
              Start Location
            </label>
            <div className="planner-input-row">
              <input
                className="panel-input"
                id="start"
                list="planner-locations"
                placeholder="Search a landmark or paste lat,lng"
                type="text"
                value={form.startLabel}
                onChange={(event) => {
                  const nextLabel = event.target.value;
                  setForm((current) => ({
                    ...current,
                    startLabel: nextLabel,
                    start: parseLocationInput(nextLabel),
                  }));
                }}
              />
              <button
                className="planner-ghost-button"
                type="button"
                onClick={onUseLocation}
              >
                Use My Location
              </button>
            </div>
            <p className="planner-helper">
              Saved Jersey City landmarks autocomplete here, or enter coordinates directly.
            </p>
          </div>

          {needsEndPoint && (
            <div className="panel-field">
              <label className="panel-label" htmlFor="end">
                End Location
              </label>
              <input
                className="panel-input"
                id="end"
                list="planner-locations"
                placeholder="Search a landmark or paste lat,lng"
                type="text"
                value={form.endLabel}
                onChange={(event) => {
                  const nextLabel = event.target.value;
                  setForm((current) => ({
                    ...current,
                    endLabel: nextLabel,
                    end: parseLocationInput(nextLabel),
                  }));
                }}
              />
            </div>
          )}

          <div className="panel-field">
            <span className="panel-label">Route Mode</span>
            <div className="planner-choice-grid">
              {ROUTE_MODES.map((mode) => (
                <button
                  key={mode.value}
                  className="planner-choice-card"
                  data-active={form.mode === mode.value}
                  type="button"
                  onClick={() => {
                    setForm((current) => ({
                      ...current,
                      mode: mode.value,
                      endLabel: mode.value === "loop" ? "" : current.endLabel,
                      end: mode.value === "loop" ? null : current.end,
                    }));
                    setError(null);
                  }}
                >
                  <span className="planner-choice-title">{mode.label}</span>
                  <span className="planner-choice-copy">{mode.blurb}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="panel-field">
            <div className="planner-inline-header">
              <span className="panel-label">Length Target</span>
              <div className="planner-pill-row">
                <button
                  className="planner-pill"
                  data-active={form.measurement === "distance"}
                  type="button"
                  onClick={() => setForm((current) => ({ ...current, measurement: "distance" }))}
                >
                  Distance
                </button>
                <button
                  className="planner-pill"
                  data-active={form.measurement === "duration"}
                  type="button"
                  onClick={() => setForm((current) => ({ ...current, measurement: "duration" }))}
                >
                  Duration
                </button>
              </div>
            </div>

            {form.measurement === "distance" ? (
              <>
                <input
                  id="distance"
                  className="planner-slider"
                  type="range"
                  min="0.5"
                  max="15"
                  step="0.5"
                  value={form.distanceMiles}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      distanceMiles: Number(event.target.value),
                    }))
                  }
                />
                <div className="planner-metric-band">
                  <span>{formatMiles(form.distanceMiles)}</span>
                  <span>{formatDuration(distanceMeters / (form.activity === "run" ? 2.4 : 1.4))}</span>
                </div>
              </>
            ) : (
              <>
                <input
                  id="duration"
                  className="planner-slider"
                  type="range"
                  min="15"
                  max="180"
                  step="5"
                  value={form.durationMinutes}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      durationMinutes: Number(event.target.value),
                    }))
                  }
                />
                <div className="planner-metric-band">
                  <span>{form.durationMinutes} min</span>
                  <span>{formatMiles(distanceMeters / 1609.34)}</span>
                </div>
              </>
            )}
          </div>

          <div className="planner-two-up">
            <div className="panel-field">
              <span className="panel-label">Activity</span>
              <div className="planner-pill-row">
                {ACTIVITY_MODES.map((activity) => (
                  <button
                    key={activity.value}
                    className="planner-pill"
                    data-active={form.activity === activity.value}
                    type="button"
                    onClick={() => setForm((current) => ({ ...current, activity: activity.value }))}
                  >
                    {activity.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="planner-summary-card">
              <span className="panel-label">Estimated Route Budget</span>
              <div className="planner-summary-metric">
                {form.measurement === "distance"
                  ? formatMiles(form.distanceMiles)
                  : `${form.durationMinutes} min`}
              </div>
              <p className="planner-summary-copy">
                {form.activity === "walk" ? "Walking pace" : "Running pace"} tuned for the request body.
              </p>
            </div>
          </div>
        </div>

        <datalist id="planner-locations">
          {LOCATION_PRESETS.map((location) => (
            <option key={location.label} value={location.label} />
          ))}
        </datalist>
      </section>

      <section className="panel-section">
        <h3 className="text-lg">Priority Mode</h3>
        <div className="planner-priority-grid mt-3">
          {PRIORITY_MODES.map((priority) => (
            <button
              key={priority.value}
              className="planner-priority-card"
              data-active={form.priority === priority.value}
              type="button"
              onClick={() => setForm((current) => ({ ...current, priority: priority.value }))}
            >
              <span className="planner-choice-title">{priority.label}</span>
              <span className="planner-choice-copy">{priority.tone}</span>
            </button>
          ))}
        </div>
        {error && (
          <div className="planner-error" role="alert">
            {error}
          </div>
        )}
        <button
          className="cta-button mt-4"
          type="button"
          disabled={loading}
          onClick={submitRoutes}
        >
          {loading ? (
            <>
              <span className="map-legend-spinner" aria-hidden="true" />
              Finding Routes
            </>
          ) : (
            "Find Routes"
          )}
        </button>
        <p className="planner-helper mt-3">
          Suggested routes appear directly on the map once they are ready.
        </p>
      </section>
    </>
  );
}

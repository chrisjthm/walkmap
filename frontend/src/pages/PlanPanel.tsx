import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../components/auth";
import { getApiBase } from "../env";
import {
  formatCoordinateLabel,
  type LocationSearchSuggestion,
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
const SEARCH_DEBOUNCE_MS = 250;
const SEARCH_MIN_QUERY_LENGTH = 3;
const SUGGESTION_LIMIT = 5;
type LocationField = "start" | "end";

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

const presetSuggestions = (query: string): LocationSearchSuggestion[] => {
  const normalizedQuery = query.trim().toLowerCase();
  const matches = LOCATION_PRESETS.filter((location) =>
    !normalizedQuery || location.label.toLowerCase().includes(normalizedQuery),
  ).slice(0, SUGGESTION_LIMIT);

  return matches.map((location) => ({
    id: `preset:${location.label}`,
    label: location.label,
    lat: location.lat,
    lng: location.lng,
    kind: "landmark",
    secondaryText: "Saved local landmark",
  }));
};

const mergeSuggestions = (
  presets: LocationSearchSuggestion[],
  remote: LocationSearchSuggestion[],
) => {
  const merged = [...presets];
  const seen = new Set(merged.map((item) => item.label.toLowerCase()));
  for (const result of remote) {
    const key = result.label.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    merged.push(result);
    seen.add(key);
  }
  return merged.slice(0, SUGGESTION_LIMIT);
};

export default function PlanPanel() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, authFetch } = useAuth();
  const {
    form,
    routes,
    selectedRouteId,
    loading,
    error,
    setForm,
    setRoutes,
    setLoading,
    setError,
    clearRoutes,
  } = useRoutePlanner();

  const apiBase = useMemo(() => getApiBase(), []);
  const [activeField, setActiveField] = useState<LocationField | null>(null);
  const [startSuggestions, setStartSuggestions] = useState<LocationSearchSuggestion[]>([]);
  const [endSuggestions, setEndSuggestions] = useState<LocationSearchSuggestion[]>([]);
  const [searchLoadingField, setSearchLoadingField] = useState<LocationField | null>(null);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [saveLoading, setSaveLoading] = useState(false);
  const blurTimeoutRef = useRef<number | null>(null);
  const needsEndPoint = form.mode !== "loop";
  const distanceMeters = measurementToMeters(
    form.measurement,
    form.distanceMiles,
    form.durationMinutes,
    form.activity,
  );
  const selectedRoute = routes.find((route) => route.routeId === selectedRouteId) ?? routes[0] ?? null;

  const onUseLocation = async () => {
    if (!navigator.geolocation) {
      setError("This browser does not support geolocation.");
      return;
    }

    setError(null);
    setSearchMessage(null);
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
          startResolvedLabel: `Current location · ${formatCoordinateLabel(next)}`,
        }));
        setStartSuggestions([]);
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

  useEffect(() => {
    const query = form.startLabel.trim();
    const parsed = parseLocationInput(form.startLabel);
    const presets = presetSuggestions(query);

    if (!query) {
      setStartSuggestions(presets);
      setSearchLoadingField((current) => (current === "start" ? null : current));
      return;
    }

    if (parsed || (form.start && form.startResolvedLabel === form.startLabel)) {
      setStartSuggestions(presets.filter((suggestion) => suggestion.label === form.startLabel));
      setSearchLoadingField((current) => (current === "start" ? null : current));
      return;
    }

    if (query.length < SEARCH_MIN_QUERY_LENGTH) {
      setStartSuggestions(presets);
      setSearchLoadingField((current) => (current === "start" ? null : current));
      return;
    }

    const timeoutId = window.setTimeout(async () => {
      setSearchLoadingField("start");
      try {
        const response = await fetch(
          `${apiBase ? `${apiBase}` : ""}/locations/search?q=${encodeURIComponent(query)}&limit=${SUGGESTION_LIMIT}`,
        );
        const payload = (await response.json()) as {
          detail?: string;
          results?: LocationSearchSuggestion[];
        };
        if (!response.ok || !Array.isArray(payload.results)) {
          throw new Error(payload.detail || "Location search is temporarily unavailable.");
        }
        setStartSuggestions(mergeSuggestions(presets, payload.results));
        setSearchMessage(null);
      } catch (searchError) {
        setStartSuggestions(presets);
        setSearchMessage(
          searchError instanceof Error
            ? searchError.message
            : "Location search is temporarily unavailable.",
        );
      } finally {
        setSearchLoadingField((current) => (current === "start" ? null : current));
      }
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [apiBase, form.start, form.startLabel, form.startResolvedLabel]);

  useEffect(() => {
    const query = form.endLabel.trim();
    const parsed = parseLocationInput(form.endLabel);
    const presets = presetSuggestions(query);

    if (!needsEndPoint) {
      setEndSuggestions([]);
      setSearchLoadingField((current) => (current === "end" ? null : current));
      return;
    }

    if (!query) {
      setEndSuggestions(presets);
      setSearchLoadingField((current) => (current === "end" ? null : current));
      return;
    }

    if (parsed || (form.end && form.endResolvedLabel === form.endLabel)) {
      setEndSuggestions(presets.filter((suggestion) => suggestion.label === form.endLabel));
      setSearchLoadingField((current) => (current === "end" ? null : current));
      return;
    }

    if (query.length < SEARCH_MIN_QUERY_LENGTH) {
      setEndSuggestions(presets);
      setSearchLoadingField((current) => (current === "end" ? null : current));
      return;
    }

    const timeoutId = window.setTimeout(async () => {
      setSearchLoadingField("end");
      try {
        const response = await fetch(
          `${apiBase ? `${apiBase}` : ""}/locations/search?q=${encodeURIComponent(query)}&limit=${SUGGESTION_LIMIT}`,
        );
        const payload = (await response.json()) as {
          detail?: string;
          results?: LocationSearchSuggestion[];
        };
        if (!response.ok || !Array.isArray(payload.results)) {
          throw new Error(payload.detail || "Location search is temporarily unavailable.");
        }
        setEndSuggestions(mergeSuggestions(presets, payload.results));
        setSearchMessage(null);
      } catch (searchError) {
        setEndSuggestions(presets);
        setSearchMessage(
          searchError instanceof Error
            ? searchError.message
            : "Location search is temporarily unavailable.",
        );
      } finally {
        setSearchLoadingField((current) => (current === "end" ? null : current));
      }
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [apiBase, form.end, form.endLabel, form.endResolvedLabel, needsEndPoint]);

  const openField = (field: LocationField) => {
    if (blurTimeoutRef.current) {
      window.clearTimeout(blurTimeoutRef.current);
      blurTimeoutRef.current = null;
    }
    setActiveField(field);
  };

  const closeFieldSoon = () => {
    blurTimeoutRef.current = window.setTimeout(() => {
      setActiveField(null);
    }, 120);
  };

  const applySuggestion = (field: LocationField, suggestion: LocationSearchSuggestion) => {
    setSearchMessage(null);
    setForm((current) => (
      field === "start"
        ? {
            ...current,
            startLabel: suggestion.label,
            start: { lat: suggestion.lat, lng: suggestion.lng },
            startResolvedLabel: suggestion.label,
          }
        : {
            ...current,
            endLabel: suggestion.label,
            end: { lat: suggestion.lat, lng: suggestion.lng },
            endResolvedLabel: suggestion.label,
          }
    ));
    if (field === "start") {
      setStartSuggestions([]);
    } else {
      setEndSuggestions([]);
    }
    setActiveField(null);
  };

  const submitRoutes = async () => {
    const start = form.start ?? parseLocationInput(form.startLabel);
    const end = needsEndPoint
      ? form.end ?? parseLocationInput(form.endLabel)
      : null;

    if (!start) {
      setError("Choose a starting point from the suggestions, use your location, or paste coordinates like 40.7178, -74.0431.");
      return;
    }

    if (needsEndPoint && !end) {
      setError("Choose an end point from the suggestions or paste coordinates before searching.");
      return;
    }

    setLoading(true);
    setError(null);
    setSaveError(null);
    setSaveSuccess(null);
    setSearchMessage(null);
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

  const saveRoute = async () => {
    if (!selectedRoute) {
      setSaveError("Find a route before saving it.");
      return;
    }

    if (!user) {
      navigate("/login", { state: { returnTo: location.pathname } });
      return;
    }

    const start = form.start ?? parseLocationInput(form.startLabel);
    const end = needsEndPoint
      ? form.end ?? parseLocationInput(form.endLabel)
      : null;

    if (!start) {
      setSaveError("Choose a starting point before saving the route.");
      return;
    }

    if (needsEndPoint && !end) {
      setSaveError("Choose an end point before saving the route.");
      return;
    }

    setSaveLoading(true);
    setSaveError(null);
    setSaveSuccess(null);

    try {
      const response = await authFetch(apiBase ? `${apiBase}/routes` : "/routes", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          start,
          end,
          mode: form.mode,
          priority: form.priority,
          segment_ids: selectedRoute.segmentIds,
          distance_m: selectedRoute.distanceM,
          duration_s: selectedRoute.durationS,
          avg_score: selectedRoute.avgScore,
        }),
      });

      const payload = (await response.json()) as { detail?: string; route_id?: string };
      if (!response.ok) {
        throw new Error(payload.detail || "We couldn’t save this route right now.");
      }

      setSaveSuccess("Route saved.");
    } catch (saveRouteError) {
      setSaveError(
        saveRouteError instanceof Error
          ? saveRouteError.message
          : "We couldn’t save this route right now.",
      );
    } finally {
      setSaveLoading(false);
    }
  };

  const renderSuggestions = (
    field: LocationField,
    suggestions: LocationSearchSuggestion[],
  ) => {
    const isOpen = activeField === field;
    if (!isOpen) {
      return null;
    }

    const isLoading = searchLoadingField === field;
    const showEmpty = !isLoading && suggestions.length === 0;

    return (
      <div className="planner-suggestions" role="listbox" aria-label={`${field} suggestions`}>
        {isLoading && (
          <div className="planner-suggestion-meta">Searching places…</div>
        )}
        {!isLoading && suggestions.map((suggestion) => (
          <button
            key={suggestion.id}
            className="planner-suggestion"
            type="button"
            onMouseDown={(event) => {
              event.preventDefault();
              applySuggestion(field, suggestion);
            }}
          >
            <span className="planner-suggestion-label">{suggestion.label}</span>
            {suggestion.secondaryText && (
              <span className="planner-suggestion-copy">
                {suggestion.secondaryText}
              </span>
            )}
          </button>
        ))}
        {showEmpty && (
          <div className="planner-suggestion-meta">
            No matches yet. Try a fuller address, business name, or landmark.
          </div>
        )}
      </div>
    );
  };

  const plannerMessage = searchMessage ?? error;

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
            <div
              className="planner-location-search"
              onFocus={() => openField("start")}
              onBlur={closeFieldSoon}
            >
              <div className="planner-input-row">
              <input
                className="panel-input"
                id="start"
                placeholder="Search a landmark or paste lat,lng"
                type="text"
                value={form.startLabel}
                onChange={(event) => {
                  const nextLabel = event.target.value;
                  const parsed = parseLocationInput(nextLabel);
                  setForm((current) => ({
                    ...current,
                    startLabel: nextLabel,
                    start: parsed,
                    startResolvedLabel:
                      parsed
                        ? nextLabel
                        : current.startResolvedLabel === nextLabel
                          ? current.startResolvedLabel
                          : null,
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
              {renderSuggestions("start", startSuggestions)}
            </div>
            <p className="planner-helper">
              Search an address, business, or landmark, or enter coordinates directly.
            </p>
          </div>

          {needsEndPoint && (
            <div className="panel-field">
              <label className="panel-label" htmlFor="end">
                End Location
              </label>
              <div
                className="planner-location-search"
                onFocus={() => openField("end")}
                onBlur={closeFieldSoon}
              >
                <input
                  className="panel-input"
                  id="end"
                  placeholder="Search a destination or paste lat,lng"
                  type="text"
                  value={form.endLabel}
                  onChange={(event) => {
                    const nextLabel = event.target.value;
                    const parsed = parseLocationInput(nextLabel);
                    setForm((current) => ({
                      ...current,
                      endLabel: nextLabel,
                      end: parsed,
                      endResolvedLabel:
                        parsed
                          ? nextLabel
                          : current.endResolvedLabel === nextLabel
                            ? current.endResolvedLabel
                            : null,
                    }));
                  }}
                />
                {renderSuggestions("end", endSuggestions)}
              </div>
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
        {plannerMessage && (
          <div className="planner-error" role="alert">
            {plannerMessage}
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
        {routes.length > 0 && (
          <>
            <button
              className="cta-button mt-4"
              type="button"
              disabled={saveLoading}
              onClick={saveRoute}
            >
              {saveLoading ? "Saving Route..." : "Save Selected Route"}
            </button>
            {saveError && (
              <div className="planner-error" role="alert">
                {saveError}
              </div>
            )}
            {saveSuccess && (
              <p className="planner-helper mt-3">{saveSuccess}</p>
            )}
          </>
        )}
      </section>
    </>
  );
}

import {
  createContext,
  type PropsWithChildren,
  useContext,
  useMemo,
  useState,
} from "react";

export type RouteMode = "loop" | "point-to-point" | "point-to-destination";
export type ActivityMode = "walk" | "run";
export type PriorityMode =
  | "highest-rated"
  | "dining"
  | "residential"
  | "explore";
export type MeasurementMode = "distance" | "duration";

export type Coordinate = {
  lat: number;
  lng: number;
};

export type LocationDraft = Coordinate & {
  label: string;
};

export type RouteSuggestion = {
  routeId: string;
  geometry: {
    type: "LineString";
    coordinates: [number, number][];
  };
  segmentIds: string[];
  distanceM: number;
  durationS: number;
  avgScore: number;
  verifiedCount: number;
  unverifiedCount: number;
};

export type RoutePlannerFormState = {
  startLabel: string;
  start: Coordinate | null;
  endLabel: string;
  end: Coordinate | null;
  mode: RouteMode;
  measurement: MeasurementMode;
  distanceMiles: number;
  durationMinutes: number;
  activity: ActivityMode;
  priority: PriorityMode;
};

type RoutePlannerContextValue = {
  form: RoutePlannerFormState;
  routes: RouteSuggestion[];
  selectedRouteId: string | null;
  previewRouteId: string | null;
  loading: boolean;
  error: string | null;
  setForm: (updater: (current: RoutePlannerFormState) => RoutePlannerFormState) => void;
  setRoutes: (routes: RouteSuggestion[]) => void;
  setSelectedRouteId: (routeId: string | null) => void;
  setPreviewRouteId: (routeId: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearRoutes: () => void;
};

const DEFAULT_FORM: RoutePlannerFormState = {
  startLabel: "Jersey City Waterfront",
  start: {
    lat: 40.7178,
    lng: -74.0431,
  },
  endLabel: "",
  end: null,
  mode: "loop",
  measurement: "distance",
  distanceMiles: 3,
  durationMinutes: 45,
  activity: "walk",
  priority: "highest-rated",
};

const RoutePlannerContext = createContext<RoutePlannerContextValue>({
  form: DEFAULT_FORM,
  routes: [],
  selectedRouteId: null,
  previewRouteId: null,
  loading: false,
  error: null,
  setForm: () => undefined,
  setRoutes: () => undefined,
  setSelectedRouteId: () => undefined,
  setPreviewRouteId: () => undefined,
  setLoading: () => undefined,
  setError: () => undefined,
  clearRoutes: () => undefined,
});

export const LOCATION_PRESETS: LocationDraft[] = [
  { label: "Jersey City Waterfront", lat: 40.7178, lng: -74.0431 },
  { label: "Grove Street PATH", lat: 40.7196, lng: -74.0431 },
  { label: "Journal Square", lat: 40.733, lng: -74.0627 },
  { label: "Liberty State Park", lat: 40.7082, lng: -74.0476 },
  { label: "Hamilton Park", lat: 40.7276, lng: -74.0452 },
];

const COORDINATE_PATTERN =
  /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/;

export function parseLocationInput(value: string): Coordinate | null {
  const preset = LOCATION_PRESETS.find(
    (location) => location.label.toLowerCase() === value.trim().toLowerCase(),
  );
  if (preset) {
    return { lat: preset.lat, lng: preset.lng };
  }

  const match = value.match(COORDINATE_PATTERN);
  if (!match) {
    return null;
  }

  const lat = Number(match[1]);
  const lng = Number(match[2]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return null;
  }
  return { lat, lng };
}

export function formatCoordinateLabel(coordinate: Coordinate): string {
  return `${coordinate.lat.toFixed(5)}, ${coordinate.lng.toFixed(5)}`;
}

export function measurementToMeters(
  measurement: MeasurementMode,
  distanceMiles: number,
  durationMinutes: number,
  activity: ActivityMode,
): number {
  if (measurement === "distance") {
    return distanceMiles * 1609.34;
  }

  const metersPerSecond = activity === "run" ? 2.4 : 1.4;
  return durationMinutes * 60 * metersPerSecond;
}

export function RoutePlannerProvider({ children }: PropsWithChildren) {
  const [form, setFormState] = useState<RoutePlannerFormState>(DEFAULT_FORM);
  const [routes, setRoutesState] = useState<RouteSuggestion[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [previewRouteId, setPreviewRouteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = useMemo<RoutePlannerContextValue>(
    () => ({
      form,
      routes,
      selectedRouteId,
      previewRouteId,
      loading,
      error,
      setForm: (updater) => {
        setFormState((current) => updater(current));
      },
      setRoutes: (nextRoutes) => {
        setRoutesState(nextRoutes);
        setSelectedRouteId(nextRoutes[0]?.routeId ?? null);
      },
      setSelectedRouteId,
      setPreviewRouteId,
      setLoading,
      setError,
      clearRoutes: () => {
        setRoutesState([]);
        setSelectedRouteId(null);
        setPreviewRouteId(null);
      },
    }),
    [error, form, loading, previewRouteId, routes, selectedRouteId],
  );

  return (
    <RoutePlannerContext.Provider value={value}>
      {children}
    </RoutePlannerContext.Provider>
  );
}

export function useRoutePlanner() {
  return useContext(RoutePlannerContext);
}

import type { FeatureCollection, LineString } from "geojson";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  buildScoreExpression,
  computeScoreAnchors,
  ScoreLegend,
} from "./mapScoreUtils";
import { getApiBase, getMapStyleUrl } from "../env";
import { useRoutePlanner } from "./routePlanner";

type SegmentProperties = {
  segment_id?: string;
  id?: string;
  name?: string;
  display_name?: string;
  composite_score?: number;
  score?: number;
  verified?: boolean;
  rating_count?: number;
  vibe_tag_counts?: Record<string, number>;
  factors?: Record<string, number>;
};

type SegmentFeature = {
  type: "Feature";
  geometry: {
    type: "LineString";
    coordinates: [number, number][];
  };
  properties: SegmentProperties;
};

type SegmentCollection = {
  type: "FeatureCollection";
  features: SegmentFeature[];
};

type SegmentDetail = {
  id: string;
  name: string;
  score: number;
  verified: boolean;
  ratingCount: number;
  vibeTags: Array<[string, number]>;
  factors: Record<string, number>;
};

const EMPTY_SEGMENTS: SegmentCollection = {
  type: "FeatureCollection",
  features: [],
};

const BASE_SCORE_COLOR_EXPRESSION = buildScoreExpression(
  0,
  100,
) as maplibregl.ExpressionSpecification;

const JERSEY_CITY_CENTER: [number, number] = [-74.036, 40.7178];

const FACTOR_LABELS: Record<string, string> = {
  road_type_positive: "Walkable road type",
  road_type_negative: "Major roadway penalty",
  sidewalk_positive: "Sidewalks present",
  sidewalk_negative: "Sidewalks missing",
  surface_positive: "Paved surface",
  surface_negative: "Unpaved surface",
  tree_cover: "Tree cover",
  waterfront: "Waterfront proximity",
  business_density: "Business density",
  park_adjacency: "Park adjacency",
  industrial_landuse: "Industrial landuse",
  residential_landuse: "Residential street",
  residential_refinement: "Residential refinement",
  speed_limit: "High speed limit",
  walkmap_sidewalk_penalty: "Residential street without sidewalks",
};

const formatFactorLabel = (key: string) => {
  if (FACTOR_LABELS[key]) {
    return FACTOR_LABELS[key];
  }
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};

const formatFactorValue = (value: number) => {
  const sign = value >= 0 ? "+" : "-";
  const abs = Math.abs(value);
  const rounded = Number.isInteger(abs) ? abs.toFixed(0) : abs.toFixed(1);
  return `${sign}${rounded}`;
};

const buildRatingBlendText = (ratingCount: number) => {
  if (ratingCount <= 0) {
    return "Score is AI-estimated - no user ratings yet";
  }
  if (ratingCount < 5) {
    return `Score is a blend of AI estimate and ${ratingCount} user rating(s)`;
  }
  return "Score is based entirely on user ratings";
};

type MapEventHandler = (event: { point: { x: number; y: number } }) => void;

type MapHandlerEntry = {
  layerId?: string;
  handler: MapEventHandler;
};

type MapSourceData = SegmentCollection;
type RouteSourceData = FeatureCollection<
  LineString,
  {
    routeId: string;
    routeIndex: number;
    selected: boolean;
  }
>;

type RouteScreenPath = {
  routeId: string;
  routeIndex: number;
  selected: boolean;
  d: string;
};

type MockSource = {
  _data: MapSourceData;
  setData: (data: MapSourceData) => void;
};

class MockMap {
  public __isMock = true;
  private container: HTMLDivElement;
  private handlers: Record<string, MapHandlerEntry[]> = {};
  private sources = new Map<string, MockSource>();
  private layers = new Map<
    string,
    { layout: Record<string, unknown>; paint: Record<string, unknown> }
  >();
  private bounds = {
    getWest: () => -74.06,
    getSouth: () => 40.708,
    getEast: () => -74.015,
    getNorth: () => 40.7282,
  };

  constructor(container: HTMLDivElement) {
    this.container = container;
    window.setTimeout(() => {
      this.emit("load");
    }, 0);
  }

  addControl() {
    return undefined;
  }

  on(event: string, layerOrHandler: string | MapEventHandler, handler?: MapEventHandler) {
    const entry: MapHandlerEntry =
      typeof layerOrHandler === "string"
        ? { layerId: layerOrHandler, handler: handler as MapEventHandler }
        : { handler: layerOrHandler };
    const list = this.handlers[event] ?? [];
    list.push(entry);
    this.handlers[event] = list;
  }

  off(event: string, layerOrHandler: string | MapEventHandler, handler?: MapEventHandler) {
    const list = this.handlers[event];
    if (!list) {
      return;
    }
    const target =
      typeof layerOrHandler === "string"
        ? handler
        : layerOrHandler;
    this.handlers[event] = list.filter((entry) => entry.handler !== target);
  }

  emit(event: string, point: { x: number; y: number } = { x: 0, y: 0 }) {
    const list = this.handlers[event] ?? [];
    list.forEach((entry) => entry.handler({ point }));
  }

  addSource(id: string, source: { type: "geojson"; data: MapSourceData }) {
    const stored: MockSource = {
      _data: source.data,
      setData: (data) => {
        stored._data = data;
      },
    };
    this.sources.set(id, stored);
  }

  getSource(id: string) {
    return this.sources.get(id);
  }

  addLayer(layer: { id: string; layout?: Record<string, unknown>; paint?: Record<string, unknown> }) {
    this.layers.set(layer.id, { layout: layer.layout ?? {}, paint: layer.paint ?? {} });
  }

  moveLayer() {
    return undefined;
  }

  getLayer(id: string) {
    return this.layers.get(id);
  }

  setLayoutProperty(id: string, property: string, value: unknown) {
    const layer = this.layers.get(id);
    if (layer) {
      layer.layout[property] = value;
    }
  }

  setPaintProperty(id: string, property: string, value: unknown) {
    const layer = this.layers.get(id);
    if (layer) {
      layer.paint[property] = value;
    }
  }

  getLayoutProperty(id: string, property: string) {
    const layer = this.layers.get(id);
    return layer?.layout[property] ?? "visible";
  }

  getBounds() {
    return this.bounds;
  }

  queryRenderedFeatures() {
    const source = this.sources.get("segments");
    return source?._data.features ?? [];
  }

  project() {
    const rect = this.container.getBoundingClientRect();
    return { x: rect.width / 2, y: rect.height / 2 };
  }

  panBy() {
    this.emit("moveend");
  }

  getCanvas() {
    return this.container;
  }

  getContainer() {
    return this.container;
  }

  isStyleLoaded() {
    return true;
  }

  remove() {
    this.handlers = {};
    this.sources.clear();
    this.layers.clear();
  }

  __triggerClick(point: { x: number; y: number }) {
    this.emit("click", point);
  }
}

const buildDetail = (props: SegmentProperties): SegmentDetail => {
  const id = props.segment_id ?? props.id ?? "unknown-segment";
  const name = props.display_name ?? props.name ?? "Unnamed segment";
  const scoreValue = Number(props.composite_score ?? props.score ?? 0);
  const verified = Boolean(props.verified);
  const ratingCount = Number(props.rating_count ?? 0);
  const tagCounts = props.vibe_tag_counts ?? {};
  const factors = props.factors ?? {};
  const vibeTags = Object.entries(tagCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  return {
    id,
    name,
    score: scoreValue,
    verified,
    ratingCount,
    vibeTags,
    factors,
  };
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

export default function MapView() {
  const {
    routes,
    selectedRouteId,
    previewRouteId,
    setSelectedRouteId,
    setPreviewRouteId,
  } = useRoutePlanner();
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const debounceRef = useRef<number | undefined>(undefined);
  const lastSegmentsRef = useRef<SegmentCollection>(EMPTY_SEGMENTS);
  const plannedRoutesRef = useRef<RouteSourceData>({
    type: "FeatureCollection",
    features: [],
  });
  const gradientInitializedRef = useRef(false);
  const [overlayVisible, setOverlayVisible] = useState(true);
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<SegmentDetail | null>(null);
  const [showScoreBreakdown, setShowScoreBreakdown] = useState(false);
  const [segmentsError, setSegmentsError] = useState(false);
  const [scoreLegend, setScoreLegend] = useState<ScoreLegend>({
    min: 0,
    max: 100,
    mode: "global",
  });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [routeScreenPaths, setRouteScreenPaths] = useState<RouteScreenPath[]>([]);
  const previousRouteCountRef = useRef(0);
  const plannedRoutes = useMemo<RouteSourceData>(
    () => {
      const activeRouteId = previewRouteId ?? selectedRouteId ?? routes[0]?.routeId ?? null;
      return {
        type: "FeatureCollection",
        features: routes.map((route, index) => ({
          type: "Feature",
          geometry: route.geometry,
          properties: {
            routeId: route.routeId,
            routeIndex: index,
            selected: activeRouteId
              ? route.routeId === activeRouteId
              : index === 0,
          },
        })),
      };
    },
    [previewRouteId, routes, selectedRouteId],
  );

  const routeOverlayViewBox = (() => {
    const container = mapContainerRef.current;
    const width = container?.clientWidth ?? 1;
    const height = container?.clientHeight ?? 1;
    return `0 0 ${Math.max(width, 1)} ${Math.max(height, 1)}`;
  })();

  useEffect(() => {
    plannedRoutesRef.current = plannedRoutes;
  }, [plannedRoutes]);

  useEffect(() => {
    setShowScoreBreakdown(false);
  }, [selectedDetail?.id]);

  const apiBase = useMemo(() => getApiBase(), []);
  const styleUrl = useMemo(() => getMapStyleUrl(), []);

  const scoreBreakdownId = selectedDetail ? `score-breakdown-${selectedDetail.id}` : undefined;
  const ratingBlendText = selectedDetail
    ? buildRatingBlendText(selectedDetail.ratingCount)
    : "";
  const factorRows = selectedDetail
    ? Object.entries(selectedDetail.factors)
        .filter(([, value]) => Boolean(value))
        .map(([key, value]) => ({
          key,
          label: formatFactorLabel(key),
          value,
          formatted: formatFactorValue(value),
        }))
    : [];

  const updateLayerVisibility = useCallback((map: maplibregl.Map) => {
    const routeModeActive = routes.length > 0;
    const verifiedVisibility = overlayVisible ? "visible" : "none";
    const unverifiedVisibility = overlayVisible && !verifiedOnly ? "visible" : "none";

    if (map.getLayer("segments-verified")) {
      map.setLayoutProperty("segments-verified", "visibility", verifiedVisibility);
      map.setPaintProperty(
        "segments-verified",
        "line-opacity",
        routeModeActive ? 0.18 : 0.9,
      );
    }
    if (map.getLayer("segments-unverified")) {
      map.setLayoutProperty(
        "segments-unverified",
        "visibility",
        unverifiedVisibility,
      );
      map.setPaintProperty(
        "segments-unverified",
        "line-opacity",
        routeModeActive ? 0.08 : 0.45,
      );
    }
  }, [overlayVisible, routes.length, verifiedOnly]);

  const updateSource = useCallback((map: maplibregl.Map, data: SegmentCollection) => {
    const source = map.getSource("segments") as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    }
  }, []);

  const updateScoreGradient = useCallback((map: maplibregl.Map, data: SegmentCollection) => {
    const { anchorLow, anchorHigh, legend } = computeScoreAnchors(data.features);
    const expression = buildScoreExpression(anchorLow, anchorHigh);

    if (map.getLayer("segments-verified")) {
      map.setPaintProperty("segments-verified", "line-color", expression);
    }
    if (map.getLayer("segments-unverified")) {
      map.setPaintProperty("segments-unverified", "line-color", expression);
    }

    setScoreLegend(legend);
  }, []);

  const ensureRouteSuggestionLayers = useCallback((map: maplibregl.Map) => {
    if (!map.getSource("route-suggestions")) {
      map.addSource("route-suggestions", {
        type: "geojson",
        data: plannedRoutesRef.current,
      });
    } else {
      const routeSource = map.getSource("route-suggestions") as
        | maplibregl.GeoJSONSource
        | undefined;
      routeSource?.setData(plannedRoutesRef.current);
    }

    if (!map.getLayer("route-suggestions")) {
      map.addLayer({
        id: "route-suggestions",
        type: "line",
        source: "route-suggestions",
        layout: {
          "line-join": "round",
          "line-cap": "round",
        },
          paint: {
            "line-color": [
            "match",
            ["get", "routeIndex"],
            0,
            "#5ca6ff",
            1,
            "#f08a47",
            2,
            "#c17bff",
            "#5ca6ff",
          ],
            "line-width": [
              "case",
              ["get", "selected"],
              ["interpolate", ["linear"], ["zoom"], 12, 5, 16, 8],
              ["interpolate", ["linear"], ["zoom"], 12, 4, 16, 6],
            ],
            "line-opacity": [
              "case",
              ["get", "selected"],
              1,
              0.78,
            ],
            "line-dasharray": [
              "case",
              ["get", "selected"],
              ["literal", [1, 0]],
              ["literal", [1.2, 1.6]],
            ],
          },
        });
    }

    if (!map.getLayer("route-suggestions-casing")) {
      map.addLayer({
        id: "route-suggestions-casing",
        type: "line",
        source: "route-suggestions",
        layout: {
          "line-join": "round",
          "line-cap": "round",
        },
        paint: {
            "line-color": [
              "case",
              ["get", "selected"],
              "rgba(247, 241, 230, 0.92)",
              "rgba(10, 18, 16, 0.88)",
            ],
            "line-width": [
              "case",
              ["get", "selected"],
              ["interpolate", ["linear"], ["zoom"], 12, 8, 16, 12],
              ["interpolate", ["linear"], ["zoom"], 12, 6, 16, 9],
            ],
            "line-opacity": [
              "case",
              ["get", "selected"],
              0.92,
              0.65,
            ],
          },
        }, "route-suggestions");
    }

    if (typeof map.moveLayer === "function") {
      if (map.getLayer("route-suggestions-casing")) {
        map.moveLayer("route-suggestions-casing");
      }
      if (map.getLayer("route-suggestions")) {
        map.moveLayer("route-suggestions");
      }
    }
  }, []);

  const updateRouteScreenPaths = useCallback((map: maplibregl.Map) => {
    const nextPaths = plannedRoutes.features
      .map((feature) => {
        const points = feature.geometry.coordinates.reduce<maplibregl.Point[]>(
          (accumulator, [lng, lat]) => {
            const point = map.project([lng, lat]);
            if (Number.isFinite(point.x) && Number.isFinite(point.y)) {
              accumulator.push(point);
            }
            return accumulator;
          },
          [],
        );

        if (points.length < 2) {
          return null;
        }

        const d = points
          .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
          .join(" ");

        return {
          routeId: feature.properties.routeId,
          routeIndex: feature.properties.routeIndex,
          selected: feature.properties.selected,
          d,
        };
      })
      .filter((path): path is RouteScreenPath => path !== null);

    setRouteScreenPaths(nextPaths);
  }, [plannedRoutes.features]);

  const fitMapToCoordinates = useCallback(
    (coordinates: [number, number][], options?: { maxZoom?: number }) => {
      const map = mapRef.current;
      if (!map || coordinates.length === 0 || typeof map.fitBounds !== "function") {
        return;
      }
      const viewportWidth = mapContainerRef.current?.clientWidth ?? window.innerWidth;
      const isDesktop = viewportWidth > 900;

      const [firstLng, firstLat] = coordinates[0];
      let minLng = firstLng;
      let maxLng = firstLng;
      let minLat = firstLat;
      let maxLat = firstLat;

      for (const [lng, lat] of coordinates) {
        minLng = Math.min(minLng, lng);
        maxLng = Math.max(maxLng, lng);
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
      }

      map.fitBounds(
        [
          [minLng, minLat],
          [maxLng, maxLat],
        ],
        {
          padding: isDesktop
            ? {
                top: 88,
                right: 96,
                bottom: 228,
                left: 452,
              }
            : {
                top: 72,
                right: 24,
                bottom: 228,
                left: 24,
              },
          duration: 950,
          maxZoom: options?.maxZoom ?? 13.75,
          pitch: 0,
          bearing: 0,
        },
      );
    },
    [],
  );

  const fetchSegments = useCallback(async (
    map: maplibregl.Map,
    options?: { refreshGradient?: boolean },
  ) => {
    const bounds = map.getBounds();
    const west = bounds.getWest();
    const south = bounds.getSouth();
    const east = bounds.getEast();
    const north = bounds.getNorth();
    const lngSpan = east - west;
    const latSpan = north - south;
    const padding = 0.15;
    const bbox = [
      west - lngSpan * padding,
      south - latSpan * padding,
      east + lngSpan * padding,
      north + latSpan * padding,
    ]
      .map((value) => value.toFixed(6))
      .join(",");

    const url = apiBase
      ? `${apiBase}/segments?bbox=${bbox}`
      : `/segments?bbox=${bbox}`;

    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error("Failed to load segments");
      }
      const data = (await response.json()) as SegmentCollection;
      setSegmentsError(false);
      updateSource(map, data);
      lastSegmentsRef.current = data;
      if (options?.refreshGradient || !gradientInitializedRef.current) {
        updateScoreGradient(map, data);
        gradientInitializedRef.current = true;
      }
      return true;
    } catch (error) {
      setSegmentsError(true);
      return false;
    }
  }, [apiBase, updateScoreGradient, updateSource]);

  const fetchSegmentDetail = useCallback(async (feature: SegmentFeature) => {
    const fallbackDetail = buildDetail(feature.properties);
    const id = fallbackDetail.id;
    const url = apiBase ? `${apiBase}/segments/${id}` : `/segments/${id}`;

    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error("Failed to load segment");
      }
      const data = (await response.json()) as SegmentProperties;
      setSelectedDetail(buildDetail({ ...feature.properties, ...data }));
    } catch (error) {
      setSelectedDetail(fallbackDetail);
    }
  }, [apiBase]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    if (import.meta.env.VITE_E2E === "true") {
      (window as Window & {
        __walkmap__?: { map?: maplibregl.Map; ready?: boolean; error?: string };
      }).__walkmap__ = {
        ready: false,
      };
    }

    let map: maplibregl.Map;
    try {
      if (import.meta.env.VITE_E2E_MOCK_MAP === "true") {
        map = new MockMap(mapContainerRef.current) as unknown as maplibregl.Map;
      } else {
        map = new maplibregl.Map({
          container: mapContainerRef.current,
          style: styleUrl,
          center: JERSEY_CITY_CENTER,
          zoom: 13.4,
          pitch: 36,
          bearing: -18,
        });
      }
    } catch (error) {
      if (import.meta.env.VITE_E2E === "true") {
        const testHook = (window as Window & {
          __walkmap__?: { map?: maplibregl.Map; ready?: boolean; error?: string };
        }).__walkmap__;
        if (testHook) {
          testHook.error = String(error ?? "failed to create map");
        }
      }
      return;
    }

    mapRef.current = map;
    if (import.meta.env.VITE_E2E === "true") {
      (window as Window & {
        __walkmap__?: { map: maplibregl.Map; ready?: boolean; error?: string };
      }).__walkmap__ = {
        map,
        ready: false,
      };
    }

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("load", () => {
      if (import.meta.env.VITE_E2E === "true") {
        const testHook = (window as Window & {
          __walkmap__?: { map: maplibregl.Map; ready?: boolean; error?: string };
        }).__walkmap__;
        if (testHook) {
          testHook.ready = true;
        }
      }
      const style = map.getStyle?.();
      if (style?.layers) {
        for (const layer of style.layers) {
          if (layer.type === "fill-extrusion" && map.getLayer(layer.id)) {
            map.removeLayer(layer.id);
          }
        }
      }
      if (!map.getSource("segments")) {
        map.addSource("segments", {
          type: "geojson",
          data: EMPTY_SEGMENTS,
        });
      }
      if (!map.getLayer("segments-unverified")) {
        map.addLayer({
          id: "segments-unverified",
          type: "line",
          source: "segments",
          filter: ["!=", ["get", "verified"], true],
          layout: {
            "line-join": "round",
            "line-cap": "round",
          },
          paint: {
            "line-color": BASE_SCORE_COLOR_EXPRESSION,
            "line-width": ["interpolate", ["linear"], ["zoom"], 14, 3, 17, 5],
            "line-opacity": 0.45,
            "line-dasharray": [2, 2],
          },
        });
      }

      if (!map.getLayer("segments-verified")) {
        map.addLayer({
          id: "segments-verified",
          type: "line",
          source: "segments",
          filter: ["==", ["get", "verified"], true],
          layout: {
            "line-join": "round",
            "line-cap": "round",
          },
          paint: {
            "line-color": BASE_SCORE_COLOR_EXPRESSION,
            "line-width": ["interpolate", ["linear"], ["zoom"], 14, 3, 17, 5],
            "line-opacity": 0.9,
          },
        });
      }

      ensureRouteSuggestionLayers(map);

      updateLayerVisibility(map);
      fetchSegments(map, { refreshGradient: true });
    });

    map.on("moveend", () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
      debounceRef.current = window.setTimeout(() => {
        fetchSegments(map);
      }, 300);
    });

    const syncRouteOverlay = () => {
      updateRouteScreenPaths(map);
    };

    map.on("move", syncRouteOverlay);
    map.on("moveend", syncRouteOverlay);
    map.on("zoom", syncRouteOverlay);
    map.on("load", syncRouteOverlay);

    const handleClick = (event: maplibregl.MapLayerMouseEvent) => {
      const features = map.queryRenderedFeatures(event.point, {
        layers: ["segments-verified", "segments-unverified"],
      }) as unknown as SegmentFeature[];

      if (!features.length) {
        return;
      }

      fetchSegmentDetail(features[0]);
    };

    map.on("click", "segments-verified", handleClick);
    map.on("click", "segments-unverified", handleClick);

    const handleEnter = () => {
      map.getCanvas().style.cursor = "pointer";
    };

    const handleLeave = () => {
      map.getCanvas().style.cursor = "";
    };

    map.on("mouseenter", "segments-verified", handleEnter);
    map.on("mouseleave", "segments-verified", handleLeave);
    map.on("mouseenter", "segments-unverified", handleEnter);
    map.on("mouseleave", "segments-unverified", handleLeave);

    map.on("error", (event) => {
      if (import.meta.env.VITE_E2E === "true") {
        const testHook = (window as Window & {
          __walkmap__?: { map: maplibregl.Map; ready?: boolean; error?: string };
        }).__walkmap__;
        if (testHook) {
          testHook.error = String(event.error ?? "unknown map error");
        }
      }
    });

    return () => {
      map.off("click", "segments-verified", handleClick);
      map.off("click", "segments-unverified", handleClick);
      map.off("move", syncRouteOverlay);
      map.off("moveend", syncRouteOverlay);
      map.off("zoom", syncRouteOverlay);
      map.off("load", syncRouteOverlay);
      map.remove();
      mapRef.current = null;
      if (import.meta.env.VITE_E2E === "true") {
        delete (window as Window & { __walkmap__?: { map: maplibregl.Map } })
          .__walkmap__;
      }
    };
  }, [apiBase, ensureRouteSuggestionLayers, fetchSegmentDetail, fetchSegments, styleUrl, updateLayerVisibility, updateRouteScreenPaths]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }
    if (!mapRef.current.isStyleLoaded()) {
      return;
    }
    ensureRouteSuggestionLayers(mapRef.current);
    updateRouteScreenPaths(mapRef.current);
  }, [ensureRouteSuggestionLayers, plannedRoutes, updateRouteScreenPaths]);

  useEffect(() => {
    if (routes.length === 0) {
      previousRouteCountRef.current = 0;
      return;
    }

    const isFreshResultSet =
      previousRouteCountRef.current === 0 || previousRouteCountRef.current !== routes.length;
    previousRouteCountRef.current = routes.length;

    if (isFreshResultSet) {
      window.scrollTo({ top: 0, behavior: "smooth" });
      fitMapToCoordinates(
        routes.flatMap((route) => route.geometry.coordinates),
        { maxZoom: 13.5 },
      );
      return;
    }

    const activeRouteId = previewRouteId ?? selectedRouteId;
    const activeRoute =
      routes.find((route) => route.routeId === activeRouteId) ?? routes[0];
    fitMapToCoordinates(activeRoute.geometry.coordinates, { maxZoom: 13.9 });
  }, [fitMapToCoordinates, previewRouteId, routes, selectedRouteId]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }
    updateLayerVisibility(mapRef.current);
  }, [updateLayerVisibility]);

  return (
    <>
      <div ref={mapContainerRef} className="map-canvas" />
      {routeScreenPaths.length > 0 && (
        <svg
          className="route-overlay-svg"
          viewBox={routeOverlayViewBox}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {[...routeScreenPaths]
            .sort((left, right) => Number(left.selected) - Number(right.selected))
            .map((path) => {
            const color = ["#5ca6ff", "#f08a47", "#c17bff"][path.routeIndex % 3];
            return (
              <g key={path.routeId}>
                <path
                  className="route-overlay-casing"
                  d={path.d}
                  style={{
                    stroke: path.selected ? "rgba(247, 241, 230, 0.95)" : "rgba(10, 18, 16, 0.88)",
                    opacity: path.selected ? 0.92 : 0.74,
                    strokeWidth: path.selected ? 14 : 9,
                  }}
                />
                <path
                  className="route-overlay-line"
                  d={path.d}
                  style={{
                    stroke: color,
                    opacity: path.selected ? 1 : 0.82,
                    strokeWidth: path.selected ? 8 : 6,
                    strokeDasharray: path.selected ? "none" : "10 10",
                  }}
                />
              </g>
            );
          })}
        </svg>
      )}
      <div className="map-surface" aria-hidden="true" />
      <div className="map-overlay">
        <div className="map-badge">Walkmap Live</div>
        <div>
          <p className="map-label">
            Aesthetic score overlays will guide every block of your route.
          </p>
        </div>
        <div className="map-card">
          {routes.length > 0 ? (
            <>
              <p className="text-sm uppercase tracking-[0.2em] text-sun">
                Route candidates live
              </p>
              <p className="mt-2 text-sm text-mist">
                {selectedRouteId
                  ? "Selected route is fully lit on the map while alternate drafts recede."
                  : "Three route drafts are layered in distinct colors across the map."}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm uppercase tracking-[0.2em] text-sun">
                Overlay status
              </p>
              <p className="mt-2 text-sm text-mist">
                {overlayVisible
                  ? "Segment scores visible across the current viewport."
                  : "Overlay hidden. Toggle it back on to view segment scores."}
              </p>
            </>
          )}
          {segmentsError && (
            <p className="mt-2 text-xs uppercase tracking-[0.2em] text-sun">
              Unable to load segments from the API.
            </p>
          )}
        </div>
      </div>

      <div className="map-controls">
        <button
          className="map-toggle"
          data-active={overlayVisible}
          type="button"
          onClick={() => setOverlayVisible((prev) => !prev)}
        >
          {overlayVisible ? "Overlay On" : "Overlay Off"}
        </button>
        <button
          className="map-toggle"
          data-active={verifiedOnly}
          type="button"
          onClick={() => setVerifiedOnly((prev) => !prev)}
        >
          Verified Only
        </button>
        <div className="map-legend" aria-live="polite">
          <div className="map-legend-bar" aria-hidden="true" />
          <div className="map-legend-text">
            Scores in view:{" "}
            <span className="map-legend-range">
              {scoreLegend.min}-{scoreLegend.max}
            </span>
            {scoreLegend.mode === "global" && (
              <span className="map-legend-note">Global scale</span>
            )}
          </div>
          <button
            className="map-legend-refresh"
            type="button"
            disabled={isRefreshing}
            onClick={async () => {
              if (!mapRef.current) {
                return;
              }
              setIsRefreshing(true);
              await fetchSegments(mapRef.current, { refreshGradient: true });
              setIsRefreshing(false);
            }}
          >
            {isRefreshing ? (
              <>
                <span className="map-legend-spinner" aria-hidden="true" />
                Refreshing
              </>
            ) : (
              "Refresh gradient"
            )}
          </button>
        </div>
      </div>

      {selectedDetail && (
        <div className="segment-card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-sun">
                Segment Detail
              </p>
              <h3 className="mt-1 text-lg">{selectedDetail.name}</h3>
            </div>
            <button
              className="map-toggle"
              type="button"
              onClick={() => setSelectedDetail(null)}
            >
              Close
            </button>
          </div>
          <div className="mt-3 grid gap-2 text-sm text-mist">
            <div className="score-row">
              <p>
                Score: <span className="text-sun">{selectedDetail.score}</span>
              </p>
              <button
                className="score-info-button"
                type="button"
                aria-label="Score breakdown"
                aria-expanded={showScoreBreakdown}
                aria-controls={scoreBreakdownId}
                onClick={() => setShowScoreBreakdown((prev) => !prev)}
              >
                ⓘ
              </button>
            </div>
            <p>
              Status: {selectedDetail.verified ? "Verified" : "Unverified"}
            </p>
            <p>Ratings: {selectedDetail.ratingCount}</p>
          </div>
          {showScoreBreakdown && (
            <div id={scoreBreakdownId} className="score-breakdown">
              <div className="score-section">
                <p className="score-section-title">AI factors</p>
                {factorRows.length > 0 ? (
                  <ul className="score-factor-list">
                    {factorRows.map((factor) => (
                      <li key={factor.key} className="score-factor-row">
                        <span>{factor.label}</span>
                        <span className="score-factor-value">{factor.formatted}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="score-empty">No AI factors available.</p>
                )}
              </div>
              <div className="score-section">
                <p className="score-section-title">User ratings</p>
                <p className="score-user-text">{ratingBlendText}</p>
              </div>
            </div>
          )}
          {selectedDetail.vibeTags.length > 0 && (
            <div className="segment-tags">
              {selectedDetail.vibeTags.map(([tag, count]) => (
                <span key={tag} className="segment-tag">
                  {tag} · {count}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {routes.length > 0 && (
        <div className="route-results-overlay">
          <div className="route-results-header">
            <p className="text-xs uppercase tracking-[0.2em] text-moss">
              Suggested Routes
            </p>
            <span className="planner-result-count">{routes.length} drafts</span>
          </div>
          <div className="route-results-list">
            {routes.map((route, index) => (
              <button
                key={route.routeId}
                className="planner-route-card route-results-card"
                data-active={(previewRouteId ?? selectedRouteId) === route.routeId}
                type="button"
                onClick={() => setSelectedRouteId(route.routeId)}
                onMouseEnter={() => setPreviewRouteId(route.routeId)}
                onMouseLeave={() => setPreviewRouteId(null)}
                onFocus={() => setPreviewRouteId(route.routeId)}
                onBlur={() => setPreviewRouteId(null)}
              >
                <div className="planner-route-header">
                  <div className="planner-route-title-row">
                    <span
                      className="planner-route-swatch"
                      style={{
                        background: ["#5ca6ff", "#f08a47", "#c17bff"][index % 3],
                      }}
                    />
                    <div>
                      <p className="planner-route-index">Route {index + 1}</p>
                      <h4>{formatMiles(route.distanceM / 1609.34)}</h4>
                    </div>
                  </div>
                  <span className="planner-score-badge">
                    Avg {Math.round(route.avgScore)}
                  </span>
                </div>
                <div className="planner-route-stats">
                  <span>{formatDuration(route.durationS)}</span>
                  <span>{route.verifiedCount} verified</span>
                  <span>{route.unverifiedCount} unverified</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {!routes.length && (
        <div className="map-style-card">
          <p className="text-xs uppercase tracking-[0.2em] text-moss">
            Map style
          </p>
          <p className="mt-2 text-sm">
            Using OpenFreeMap via <span className="font-semibold">{styleUrl}</span>.
            Override with <span className="font-semibold">VITE_MAP_STYLE_URL</span>{" "}
            if needed.
          </p>
        </div>
      )}
    </>
  );
}

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";

type SegmentProperties = {
  segment_id?: string;
  id?: string;
  name?: string;
  composite_score?: number;
  score?: number;
  verified?: boolean;
  rating_count?: number;
  vibe_tag_counts?: Record<string, number>;
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
};

const EMPTY_SEGMENTS: SegmentCollection = {
  type: "FeatureCollection",
  features: [],
};

const SCORE_COLOR_EXPRESSION = [
  "interpolate",
  ["linear"],
  ["coalesce", ["get", "composite_score"], ["get", "score"], 0],
  0,
  "#d64545",
  20,
  "#e78b3c",
  40,
  "#f2d15c",
  60,
  "#8ccf7a",
  80,
  "#2f7f4f",
  100,
  "#1f6a3f",
] as maplibregl.ExpressionSpecification;

const JERSEY_CITY_CENTER: [number, number] = [-74.036, 40.7178];

const getApiBase = () => {
  const rawBase = import.meta.env.VITE_API_BASE_URL;
  if (!rawBase) {
    return "";
  }
  return rawBase.endsWith("/") ? rawBase.slice(0, -1) : rawBase;
};

type MapEventHandler = (event: { point: { x: number; y: number } }) => void;

type MapHandlerEntry = {
  layerId?: string;
  handler: MapEventHandler;
};

type MapSourceData = SegmentCollection;

type MockSource = {
  _data: MapSourceData;
  setData: (data: MapSourceData) => void;
};

class MockMap {
  public __isMock = true;
  private container: HTMLDivElement;
  private handlers: Record<string, MapHandlerEntry[]> = {};
  private sources = new Map<string, MockSource>();
  private layers = new Map<string, { layout: Record<string, unknown> }>();
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

  addLayer(layer: { id: string; layout?: Record<string, unknown> }) {
    this.layers.set(layer.id, { layout: layer.layout ?? {} });
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
  const name = props.name ?? "Unnamed segment";
  const scoreValue = Number(props.composite_score ?? props.score ?? 0);
  const verified = Boolean(props.verified);
  const ratingCount = Number(props.rating_count ?? 0);
  const tagCounts = props.vibe_tag_counts ?? {};
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
  };
};

export default function MapView() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const debounceRef = useRef<number | undefined>(undefined);
  const [overlayVisible, setOverlayVisible] = useState(true);
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<SegmentDetail | null>(null);
  const [segmentsError, setSegmentsError] = useState(false);

  const apiBase = useMemo(() => getApiBase(), []);
  const styleUrl = useMemo(
    () =>
      import.meta.env.VITE_MAP_STYLE_URL ??
      "https://tiles.openfreemap.org/styles/liberty",
    [],
  );

  const updateLayerVisibility = (map: maplibregl.Map) => {
    const verifiedVisibility = overlayVisible ? "visible" : "none";
    const unverifiedVisibility =
      overlayVisible && !verifiedOnly ? "visible" : "none";

    if (map.getLayer("segments-verified")) {
      map.setLayoutProperty("segments-verified", "visibility", verifiedVisibility);
    }
    if (map.getLayer("segments-unverified")) {
      map.setLayoutProperty(
        "segments-unverified",
        "visibility",
        unverifiedVisibility,
      );
    }
  };

  const updateSource = (map: maplibregl.Map, data: SegmentCollection) => {
    const source = map.getSource("segments") as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    }
  };

  const fetchSegments = async (map: maplibregl.Map) => {
    const bounds = map.getBounds();
    const bbox = [
      bounds.getWest(),
      bounds.getSouth(),
      bounds.getEast(),
      bounds.getNorth(),
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
    } catch (error) {
      setSegmentsError(true);
    }
  };

  const fetchSegmentDetail = async (feature: SegmentFeature) => {
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
  };

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
            "line-color": SCORE_COLOR_EXPRESSION,
            "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2.4, 16, 4.8],
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
            "line-color": SCORE_COLOR_EXPRESSION,
            "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2.8, 16, 5.6],
            "line-opacity": 0.9,
          },
        });
      }

      updateLayerVisibility(map);
      fetchSegments(map);
    });

    map.on("moveend", () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
      debounceRef.current = window.setTimeout(() => {
        fetchSegments(map);
      }, 300);
    });

    const handleClick = (event: maplibregl.MapLayerMouseEvent) => {
      const features = map.queryRenderedFeatures(event.point, {
        layers: ["segments-verified", "segments-unverified"],
      }) as SegmentFeature[];

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
      map.remove();
      mapRef.current = null;
      if (import.meta.env.VITE_E2E === "true") {
        delete (window as Window & { __walkmap__?: { map: maplibregl.Map } })
          .__walkmap__;
      }
    };
  }, [apiBase, styleUrl]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }
    updateLayerVisibility(mapRef.current);
  }, [overlayVisible, verifiedOnly]);

  return (
    <>
      <div ref={mapContainerRef} className="map-canvas" />
      <div className="map-surface" aria-hidden="true" />
      <div className="map-overlay">
        <div className="map-badge">Walkmap Live</div>
        <div>
          <p className="map-label">
            Aesthetic score overlays will guide every block of your route.
          </p>
        </div>
        <div className="map-card">
          <p className="text-sm uppercase tracking-[0.2em] text-sun">
            Overlay status
          </p>
          <p className="mt-2 text-sm text-mist">
            {overlayVisible
              ? "Segment scores visible across the current viewport."
              : "Overlay hidden. Toggle it back on to view segment scores."}
          </p>
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
            <p>
              Score: <span className="text-sun">{selectedDetail.score}</span>
            </p>
            <p>
              Status: {selectedDetail.verified ? "Verified" : "Unverified"}
            </p>
            <p>Ratings: {selectedDetail.ratingCount}</p>
          </div>
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
    </>
  );
}

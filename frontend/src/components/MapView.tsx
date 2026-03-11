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

const FALLBACK_SEGMENTS: SegmentCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-74.0415, 40.716],
          [-74.036, 40.7206],
        ],
      },
      properties: {
        segment_id: "mock-hudson-01",
        name: "Hudson Promenade",
        composite_score: 87,
        verified: true,
        rating_count: 18,
        vibe_tag_counts: { waterfront: 10, scenic: 6, breezy: 4 },
      },
    },
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-74.0492, 40.7188],
          [-74.045, 40.722],
        ],
      },
      properties: {
        segment_id: "mock-grove-02",
        name: "Grove Street",
        composite_score: 62,
        verified: false,
        rating_count: 4,
        vibe_tag_counts: { cafes: 3, lively: 2 },
      },
    },
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-74.033, 40.7115],
          [-74.028, 40.714],
        ],
      },
      properties: {
        segment_id: "mock-liberty-03",
        name: "Liberty State Park",
        composite_score: 74,
        verified: true,
        rating_count: 9,
        vibe_tag_counts: { parks: 5, quiet: 3 },
      },
    },
  ],
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
  const [usingFallback, setUsingFallback] = useState(false);

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
      setUsingFallback(false);
      updateSource(map, data);
    } catch (error) {
      setUsingFallback(true);
      updateSource(map, FALLBACK_SEGMENTS);
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

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: styleUrl,
      center: JERSEY_CITY_CENTER,
      zoom: 13.4,
      pitch: 36,
      bearing: -18,
    });

    mapRef.current = map;

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("load", () => {
      if (!map.getSource("segments")) {
        map.addSource("segments", {
          type: "geojson",
          data: FALLBACK_SEGMENTS,
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

    return () => {
      map.off("click", "segments-verified", handleClick);
      map.off("click", "segments-unverified", handleClick);
      map.remove();
      mapRef.current = null;
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
          {usingFallback && (
            <p className="mt-2 text-xs uppercase tracking-[0.2em] text-sun">
              Mock data (API offline)
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

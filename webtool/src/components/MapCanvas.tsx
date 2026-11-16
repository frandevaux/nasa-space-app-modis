'use client';
/*
 * Base colors are the prototype's flat palette darkened 15 % so the UI panels stand out.
 * MapLibre map without a tile basemap: IGN provinces and departments drawn in the prototype's flat style.
 * Layers:
 * Two views:
 *   - fires (main): "fire-heat" blob of fire centroids far away (heatmap in 4 bands, like the prototype's
 *     #franjas SVG filter) and the real fire polygons (union of pixel circles, PLAN T16) once zoomed in.
 *   - hotspots (alternative): "heat" blob, then each hotspot as a circle with its real pixel radius (PLAN T11).
 *   - forecast days, in YELLOW so estimates never look like the historical record (orange):
 *       fires view: "pred-fire-heat" blob far away and the predicted fire OUTLINES close up ("pred-fire-*");
 *       hotspots view: "pred-heat" blob and "pred-hs" circles (1 km cells, r = half the diagonal).
 * Data credits live under the legend (MapView), not in a map control.
 */
import { useEffect, useRef } from 'react';
import maplibregl, { type GeoJSONSource, type Map as MLMap, type Marker } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { getGeo } from '@/lib/data';
import type { LogEntry, Region } from '@/lib/types';

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const ACCENT = '#C2410C';

// Pixel radius ≈ r_m / metres-per-pixel; for 512 px tiles at ~33° S, mpp ≈ 65748 / 2^z.
const radiusAt = (z: number) => ['max', 1.5, ['*', ['get', 'r'], 2 ** z / 65748]];

export interface Padding { top: number; bottom: number; left: number; right: number }

/** Shrinks the padding when the panels would leave no room for the map (small screens), avoiding NaN cameras. */
function safePadding(map: MLMap, p: Padding): Padding {
  const { clientWidth: w, clientHeight: h } = map.getContainer();
  const fx = p.left + p.right > w * 0.8 ? (w * 0.8) / (p.left + p.right) : 1;
  const fy = p.top + p.bottom > h * 0.8 ? (h * 0.8) / (p.top + p.bottom) : 1;
  return { left: p.left * fx, right: p.right * fx, top: p.top * fy, bottom: p.bottom * fy };
}

export type MapViewMode = 'fires' | 'hotspots';

const HEAT_COLOR = ['step', ['heatmap-density'],
  'rgba(232,89,12,0)', 0.1, 'rgba(232,89,12,0.2)', 0.35, 'rgba(232,89,12,0.42)', 0.65, 'rgba(232,89,12,0.66)', 0.9, 'rgba(232,89,12,0.92)'];
// Forecast blob: same bands and opacities as the historical one (HEAT_COLOR), only the hue changes to yellow.
const PRED_HEAT = ['step', ['heatmap-density'],
  'rgba(214,166,0,0)', 0.1, 'rgba(214,166,0,0.2)', 0.35, 'rgba(214,166,0,0.42)', 0.65, 'rgba(214,166,0,0.66)', 0.9, 'rgba(214,166,0,0.92)'];
/*
 * Forecast blobs use the same intensity / radius / fade as their historical twins. The historical weight
 * includes the fire confidence; the forecast has no comparable score, so it uses the historical median
 * confidence in Córdoba (≈ 0.48): a predicted fire weighs like a typical observed fire of the same size.
 */
const PRED_WEIGHT = 0.48;
// Predicted fires: colour by size (hotspots per fire: 1 · 2–3 · 4–9 · 10+), never by the model score.
const PRED_SIZE_COLOR = ['step', ['get', 'n'], '#F9EB9C', 2, '#F5DA55', 4, '#EBC21F', 10, '#C99A06'];
const CONF_COLOR = ['interpolate', ['linear'], ['get', 'conf'], 10, '#F4B08A', 50, '#E8743B', 90, ACCENT];

interface Props {
  view: MapViewMode;
  fires: { polygons: GeoJSON.FeatureCollection; points: GeoJSON.FeatureCollection };
  selectedFire: string | null;
  /** Firewave of the selected fire: all its fires get a dashed outline. */
  selectedWave: string | null;
  hotspots: GeoJSON.FeatureCollection;
  /** Predicted hotspots of the forecast days (empty outside them or in the fires view). */
  forecast: GeoJSON.FeatureCollection;
  /** Predicted fires (outlines + centroids) of the forecast days (empty outside them or in the hotspots view). */
  forecastFires: { polygons: GeoJSON.FeatureCollection; points: GeoJSON.FeatureCollection };
  region: Region | null;
  showEntries: boolean;
  entries: LogEntry[];
  selectedEntry: string | null;
  point: { lat: number; lon: number } | null;
  padding: Padding;
  /** Fly to this point when `key` changes (e.g. a field-log entry was selected). */
  focus: { lat: number; lon: number; key: string } | null;
  onClick: (lat: number, lon: number) => void;
  onHover: (h: { lat: number; lon: number; x: number; y: number } | null) => void;
  onEntryClick: (e: LogEntry) => void;
}

export default function MapCanvas(props: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const ready = useRef(false);
  const latest = useRef(props);
  latest.current = props;
  const entryMarkers = useRef<Marker[]>([]);
  const pointMarker = useRef<Marker | null>(null);

  /* --- create the map once --- */
  useEffect(() => {
    if (!el.current) { return; }
    const map = new maplibregl.Map({
      container: el.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#B9B9B9' } }],
      },
      center: [-64, -38],
      zoom: 3.4,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;

    map.on('load', async () => {
      const [prov, dept] = await Promise.all([getGeo('provinces'), getGeo('departments')]);
      map.addSource('prov', { type: 'geojson', data: prov });
      map.addSource('dept', { type: 'geojson', data: dept });
      map.addSource('hs', { type: 'geojson', data: EMPTY });
      map.addSource('fire-poly', { type: 'geojson', data: EMPTY });
      map.addSource('fire-pts', { type: 'geojson', data: EMPTY });
      map.addSource('pred', { type: 'geojson', data: EMPTY });
      map.addSource('pred-poly', { type: 'geojson', data: EMPTY });
      map.addSource('pred-pts', { type: 'geojson', data: EMPTY });

      map.addLayer({ id: 'prov-fill', type: 'fill', source: 'prov', paint: { 'fill-color': '#D9D9D9' } });
      map.addLayer({ id: 'dept-line', type: 'line', source: 'dept', paint: { 'line-color': '#AEB2B8', 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.3, 9, 1] } });
      map.addLayer({ id: 'prov-line', type: 'line', source: 'prov', paint: { 'line-color': '#787E86', 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 9, 1.6] } });
      map.addLayer({
        id: 'pred-heat', type: 'heatmap', source: 'pred', maxzoom: 11,
        paint: {
          'heatmap-weight': ['*', PRED_WEIGHT, ['get', 'f']],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 3, 0.25, 7, 0.45, 10, 0.9],
          'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 3, 2.5, 7, 8, 10, 24],
          'heatmap-color': PRED_HEAT as never,
          'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 8, 1, 11, 0],
        },
      });
      map.addLayer({
        id: 'pred-hs', type: 'circle', source: 'pred', minzoom: 7.5,
        paint: {
          'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 8, radiusAt(8), 16, radiusAt(16)] as never,
          'circle-color': PRED_SIZE_COLOR as never,
          'circle-opacity': ['interpolate', ['linear'], ['zoom'], 7.5, 0, 9, ['*', 0.75, ['get', 'f']]],
          'circle-stroke-color': '#8A6A00',
          'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 9, 0, 12, 0.8],
        },
      });
      map.addLayer({
        id: 'heat', type: 'heatmap', source: 'hs', maxzoom: 11,
        paint: {
          'heatmap-weight': ['*', ['/', ['get', 'p'], 100], ['get', 'f']],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 3, 0.25, 7, 0.45, 10, 0.9],
          'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 3, 2.5, 7, 8, 10, 24],
          'heatmap-color': HEAT_COLOR as never,
          'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 8, 1, 11, 0],
        },
      });
      map.addLayer({
        id: 'hs', type: 'circle', source: 'hs', minzoom: 8,
        paint: {
          'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 8, radiusAt(8), 16, radiusAt(16)] as never,
          'circle-color': ['interpolate', ['linear'], ['get', 'p'], 10, '#F4B08A', 50, '#E8743B', 90, ACCENT],
          'circle-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0, 9.5, ['*', 0.6, ['get', 'f']]],
          'circle-stroke-color': ['case', ['==', ['get', 's'], 1], '#7C2D12', '#3D434B'],
          'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 9, 0, 12, 0.6],
        },
      });
      // Fires: blob far away, real polygons close up.
      map.addLayer({
        id: 'fire-heat', type: 'heatmap', source: 'fire-pts', maxzoom: 10,
        paint: {
          'heatmap-weight': ['*', ['/', ['get', 'conf'], 100], ['get', 'f'], ['min', 3, ['+', 0.6, ['^', ['get', 'km2'], 0.5]]]],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 3, 0.35, 7, 0.6, 9, 1],
          'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 3, 3, 7, 9, 9, 22],
          'heatmap-color': HEAT_COLOR as never,
          'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 7.5, 1, 9.5, 0],
        },
      });
      map.addLayer({
        id: 'fire-fill', type: 'fill', source: 'fire-poly', minzoom: 6.5,
        paint: {
          'fill-color': CONF_COLOR as never,
          'fill-opacity': ['interpolate', ['linear'], ['zoom'], 6.5, 0, 8.5, ['*', 0.75, ['get', 'f']]],
        },
      });
      map.addLayer({
        id: 'fire-line', type: 'line', source: 'fire-poly', minzoom: 9,
        paint: { 'line-color': '#7C2D12', 'line-width': 0.7, 'line-opacity': ['*', 0.8, ['get', 'f']] },
      });
      map.addLayer({
        id: 'fire-wave', type: 'line', source: 'fire-poly', filter: ['==', ['get', 'ev'], '__none__'],
        paint: { 'line-color': '#17191C', 'line-width': 1.4, 'line-dasharray': [2, 1.5] },
      });
      map.addLayer({
        id: 'fire-sel', type: 'line', source: 'fire-poly', filter: ['==', ['get', 'id'], ''],
        paint: { 'line-color': '#17191C', 'line-width': 2.2 },
      });
      // Predicted fires: blob far away, outlines close up (same as the historical fires, in yellow).
      map.addLayer({
        id: 'pred-fire-heat', type: 'heatmap', source: 'pred-pts', maxzoom: 10,
        paint: {
          'heatmap-weight': ['*', PRED_WEIGHT, ['get', 'f'], ['min', 3, ['+', 0.6, ['^', ['get', 'km2'], 0.5]]]],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 3, 0.35, 7, 0.6, 9, 1],
          'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 3, 3, 7, 9, 9, 22],
          'heatmap-color': PRED_HEAT as never,
          'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 7.5, 1, 9.5, 0],
        },
      });
      map.addLayer({
        id: 'pred-fire-fill', type: 'fill', source: 'pred-poly', minzoom: 6,
        paint: {
          'fill-color': PRED_SIZE_COLOR as never,
          'fill-opacity': ['interpolate', ['linear'], ['zoom'], 6, 0, 8, ['*', 0.8, ['get', 'f']]],
        },
      });
      map.addLayer({
        id: 'pred-fire-line', type: 'line', source: 'pred-poly', minzoom: 7.5,
        paint: { 'line-color': '#8A6A00', 'line-width': 0.9, 'line-opacity': ['*', 0.9, ['get', 'f']] },
      });
      map.addLayer({
        id: 'pred-fire-wave', type: 'line', source: 'pred-poly', filter: ['==', ['get', 'ev'], '__none__'],
        paint: { 'line-color': '#17191C', 'line-width': 1.4, 'line-dasharray': [2, 1.5] },
      });
      map.addLayer({
        id: 'pred-fire-sel', type: 'line', source: 'pred-poly', filter: ['==', ['get', 'id'], ''],
        paint: { 'line-color': '#17191C', 'line-width': 2.2 },
      });
      map.addLayer({ id: 'sel-line', type: 'line', source: 'prov', filter: ['==', ['get', 'id'], ''], paint: { 'line-color': '#17191C', 'line-width': 2.2 } });
      map.addLayer({ id: 'sel-dept-line', type: 'line', source: 'dept', filter: ['==', ['get', 'id'], ''], paint: { 'line-color': '#17191C', 'line-width': 2.2 } });

      ready.current = true;
      syncData();
      syncRegion(true);
    });

    map.on('click', (e) => latest.current.onClick(e.lngLat.lat, e.lngLat.lng));
    map.on('mousemove', (e) => latest.current.onHover({ lat: e.lngLat.lat, lon: e.lngLat.lng, x: e.point.x, y: e.point.y }));
    map.on('mouseout', () => latest.current.onHover(null));

    return () => {
      ready.current = false;
      map.remove();
      mapRef.current = null;
    };
     
  }, []);

  function syncData() {
    const map = mapRef.current;
    if (!map || !ready.current) { return; }
    const p = latest.current;
    (map.getSource('hs') as GeoJSONSource).setData(p.view === 'hotspots' ? p.hotspots : EMPTY);
    (map.getSource('fire-poly') as GeoJSONSource).setData(p.view === 'fires' ? p.fires.polygons : EMPTY);
    (map.getSource('fire-pts') as GeoJSONSource).setData(p.view === 'fires' ? p.fires.points : EMPTY);
    (map.getSource('pred') as GeoJSONSource).setData(p.forecast);
    (map.getSource('pred-poly') as GeoJSONSource).setData(p.forecastFires.polygons);
    (map.getSource('pred-pts') as GeoJSONSource).setData(p.forecastFires.points);
    map.setFilter('pred-fire-sel', ['==', ['get', 'id'], p.selectedFire ?? '']);
    const wave = ['==', ['get', 'ev'], p.selectedWave || '__none__'];
    map.setFilter('fire-wave', wave as never);
    map.setFilter('pred-fire-wave', wave as never);
    const vis = (on: boolean) => (on ? 'visible' : 'none');
    for (const id of ['heat', 'hs']) { map.setLayoutProperty(id, 'visibility', vis(p.view === 'hotspots')); }
    for (const id of ['fire-heat', 'fire-fill', 'fire-line', 'fire-wave', 'fire-sel']) { map.setLayoutProperty(id, 'visibility', vis(p.view === 'fires')); }
    map.setFilter('fire-sel', ['==', ['get', 'id'], p.selectedFire ?? '']);
  }

  function syncRegion(initial = false) {
    const map = mapRef.current;
    const r = latest.current.region;
    if (!map || !ready.current || !r) { return; }
    map.setFilter('sel-line', ['==', ['get', 'id'], r.kind === 'province' ? r.id : '']);
    map.setFilter('sel-dept-line', ['==', ['get', 'id'], r.kind === 'department' ? r.id : '']);
    map.fitBounds(r.bbox, { padding: safePadding(map, latest.current.padding), duration: initial ? 0 : 900, maxZoom: 11 });
  }

  useEffect(syncData, [props.hotspots, props.fires, props.forecast, props.forecastFires, props.view, props.selectedFire, props.selectedWave]);
   
  useEffect(() => syncRegion(), [props.region?.id]);

  /* --- field-log pins (DOM markers) --- */
  useEffect(() => {
    const map = mapRef.current;
    entryMarkers.current.forEach((m) => m.remove());
    entryMarkers.current = [];
    if (!map || !props.showEntries) { return; }
    for (const e of props.entries) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pin-marker';
      b.setAttribute('aria-label', `Registro: ${e.title}, ${e.date}`);
      b.setAttribute('aria-pressed', String(e.id === props.selectedEntry));
      b.addEventListener('click', (ev) => { ev.stopPropagation(); latest.current.onEntryClick(e); });
      entryMarkers.current.push(new maplibregl.Marker({ element: b }).setLngLat([e.lon, e.lat]).addTo(map));
    }
  }, [props.entries, props.showEntries, props.selectedEntry]);

  /* --- fly to a focus point --- */
  useEffect(() => {
    const map = mapRef.current;
    const f = props.focus;
    if (!map || !f) { return; }
    map.flyTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 9), padding: safePadding(map, latest.current.padding), duration: 900 });
  }, [props.focus?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  /* --- selected point --- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) { return; }
    if (!props.point) { pointMarker.current?.remove(); pointMarker.current = null; return; }
    if (!pointMarker.current) {
      const d = document.createElement('div');
      d.className = 'point-marker';
      pointMarker.current = new maplibregl.Marker({ element: d });
    }
    pointMarker.current.setLngLat([props.point.lon, props.point.lat]).addTo(map);
  }, [props.point]);

  return <div ref={el} className="map__canvas" />;
}

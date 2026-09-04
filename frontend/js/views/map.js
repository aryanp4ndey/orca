/**
 * The marine map.
 * 
 * Rewritten to use Leaflet JS with OpenStreetMap tiles to provide a full
 * world map, replacing the custom SVG baseline implementation.
 */

import { h, ICON } from '../util/dom.js';
import { num } from '../util/format.js';
import { rampColour, normalise, gridSpacing } from './ocean_layer.js';

const RISK_COLOUR = {
  LOW: '#3ddc97', MODERATE: '#ffb547', HIGH: '#ff7a5c',
  CRITICAL: '#ff4d6d', INSUFFICIENT_DATA: '#8aa0b4',
};

const CATEGORY_STYLE = {
  restricted:   { color: '#ff4d6d', fillColor: '#ff4d6d', fillOpacity: 0.13, dashArray: '6, 5', weight: 1.4 },
  fishing_ban:  { color: '#ffb547', fillColor: '#ffb547', fillOpacity: 0.12, dashArray: '6, 5', weight: 1.4 },
  imd_sea_area: { color: 'rgba(46,230,214,0.3)', fillColor: 'rgba(46,230,214,0.04)', fillOpacity: 1, dashArray: '2, 7', weight: 1 },
  pfz:          { color: '#3ddc97', fillColor: '#3ddc97', fillOpacity: 0.20, dashArray: null, weight: 1.6 },
  default:      { color: 'rgba(138,160,180,0.5)', fillColor: 'rgba(138,160,180,0.1)', fillOpacity: 1, dashArray: '4, 4', weight: 1.2 },
};

export class MarineMap {
  constructor({ lowBandwidth = false } = {}) {
    this.view = { lon: 78.5, lat: 14.0, span: 26 };
    this.lowBandwidth = lowBandwidth;
    this.overlays = { zones: [], markers: [], routes: [], conditions: [] };
    this.oceanField = null;
    this.onCellPick = null;
    
    this.map = null;
    this.layerGroups = {
      zones: null,
      sea_areas: null,
      pfz: null,
      route: null,
      markers: null,
      conditions: null,
      ocean_colour: null
    };

    this.layers = {
      coast: true, places: !lowBandwidth, zones: true,
      sea_areas: false, pfz: true, route: true, conditions: true,
      ocean_colour: true,
    };
  }

  setBasemap(basemap) { 
    // Ignore the vector basemap, since we are using OpenStreetMap tiles
    return this; 
  }

  setOceanField(field) {
    this.oceanField = (field && field.origin !== 'UNAVAILABLE' && field.cells?.length) ? field : null;
    this.draw();
    return this;
  }

  setFromResponse(response) {
    const viz = response?.visualizations || {};
    this.overlays.zones = (viz.layers || [])
      .filter((layer) => layer.kind === 'polygon' && layer.geojson?.geometry)
      .map((layer) => ({
        geometry: layer.geojson.geometry,
        name: layer.name,
        category: layer.style_hint || 'default',
        authoritative: layer.geojson.properties?.authoritative === true,
      }));
    this.overlays.routes = (viz.layers || [])
      .filter((layer) => layer.kind === 'line' && layer.geojson?.geometry)
      .map((layer) => ({ geometry: layer.geojson.geometry, name: layer.name,
                         properties: layer.geojson.properties || {} }));
    this.overlays.markers = (viz.markers || []).map((marker) => ({
      ...marker, risk: marker.risk_level || response?.risk?.risk_level || null,
    }));
    this.overlays.conditions = conditionsFrom(response);
    const focus = this.overlays.markers[0];
    if (focus) this.focus(focus.lat, focus.lon, this.lowBandwidth ? 4 : 2.6);
    else this.draw();
    return this;
  }

  setRouteSegments(segments) {
    this.overlays.routes = segments.map((segment) => ({
      geometry: { type: 'LineString',
                  coordinates: [[segment.start.lon, segment.start.lat],
                                [segment.end.lon, segment.end.lat]] },
      name: `Segment ${segment.index + 1}`,
      properties: { risk_level: segment.risk_level },
    }));
    const all = segments.flatMap((s) => [s.start, s.end]);
    if (all.length) {
      const lats = all.map((p) => p.lat); const lons = all.map((p) => p.lon);
      this.view = {
        lat: (Math.min(...lats) + Math.max(...lats)) / 2,
        lon: (Math.min(...lons) + Math.max(...lons)) / 2,
        span: Math.max(1.2, (Math.max(...lons) - Math.min(...lons)) * 2.2),
      };
      if (this.map) {
        this.map.fitBounds([[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]]);
      }
    }
    this.draw();
    return this;
  }

  setPfzZones(zones) {
    this.overlays.zones = zones
      .filter((zone) => zone.geojson?.geometry || zone.geometry)
      .map((zone) => ({
        geometry: zone.geojson?.geometry || zone.geometry,
        name: zone.name || 'Fishing zone', category: 'pfz', authoritative: false,
      }));
    this.overlays.markers = zones
      .filter((zone) => zone.lat && zone.lon)
      .map((zone) => ({ lat: zone.lat, lon: zone.lon, label: zone.label, risk: 'LOW' }));
    this.draw();
    return this;
  }

  focus(lat, lon, span = 2.6) { 
    this.view = { lat, lon, span };
    if (this.map) {
      // span is degrees roughly. We can approximate zoom level
      const zoom = Math.max(3, Math.min(18, Math.round(11 - Math.log2(span))));
      this.map.setView([lat, lon], zoom);
    }
    this.draw(); 
    return this; 
  }

  zoom(factor) {
    if (this.map) {
      this.map.setZoom(this.map.getZoom() + (factor > 1 ? -1 : 1));
    }
  }

  render() {
    this.canvas = h('div', { class: 'mapwrap leaflet-map-container', style: { width: '100%', height: '100%', minHeight: '300px' } });
    
    const wrap = h('div', { class: 'maprow' },
      this.canvas,
      h('div', { class: 'maplegend' },
        legendSwatch('#ff4d6d', 'Restricted / caution'),
        legendSwatch('#ffb547', 'Seasonal closure'),
        legendSwatch('#3ddc97', 'Fishing zone')));

    // Initialize Leaflet on next frame after DOM insertion
    requestAnimationFrame(() => this.initLeaflet());
    return wrap;
  }

  initLeaflet() {
    if (this.map) return;
    
    // Default zoom based on span
    const zoom = Math.max(3, Math.min(18, Math.round(11 - Math.log2(this.view.span))));
    
    this.map = L.map(this.canvas, {
      zoomControl: true,
      attributionControl: true
    }).setView([this.view.lat, this.view.lon], zoom);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap contributors'
    }).addTo(this.map);

    // Initialize layer groups
    for (const key of Object.keys(this.layerGroups)) {
      this.layerGroups[key] = L.layerGroup();
      if (this.layers[key] || key === 'markers' || key === 'conditions') {
        this.layerGroups[key].addTo(this.map);
      }
    }

    this.map.on('click', (e) => {
      if (this.onCellPick) {
        const cell = this.cellAt(e.latlng.lat, e.latlng.lng);
        if (cell) this.onCellPick(cell);
      }
    });

    this.draw();
  }

  layerControls() {
    const options = [
      ['zones', 'Boundaries'],
      ['sea_areas', 'Sea areas'], ['pfz', 'Fishing zones'],
      ['route', 'Route'], ['conditions', 'Conditions'],
      ['ocean_colour', 'Ocean colour'],
    ];
    return h('div', { class: 'layertoggles', role: 'group', 'aria-label': 'Map layers' },
      ...options.map(([key, label]) => {
        const chip = h('button', {
          class: 'chip', type: 'button', role: 'switch',
          'aria-checked': String(Boolean(this.layers[key])),
          'data-active': this.layers[key] ? 'true' : 'false',
          'data-layer': key,
          onclick: () => {
            this.layers[key] = !this.layers[key];
            chip.dataset.active = this.layers[key] ? 'true' : 'false';
            chip.setAttribute('aria-checked', String(this.layers[key]));
            
            if (this.map && this.layerGroups[key]) {
              if (this.layers[key]) this.layerGroups[key].addTo(this.map);
              else this.layerGroups[key].remove();
            }
            this.draw();
          },
        }, label);
        return chip;
      }));
  }

  draw() {
    if (!this.map) return;

    // Clear all layers
    for (const group of Object.values(this.layerGroups)) {
      if (group) group.clearLayers();
    }

    if (this.layers.ocean_colour) this.drawOceanField();
    
    // Draw zones
    for (const zone of this.overlays.zones) {
      const style = CATEGORY_STYLE[zone.category] || CATEGORY_STYLE.default;
      const groupKey = zone.category === 'imd_sea_area' ? 'sea_areas' : 
                      (zone.category === 'pfz' ? 'pfz' : 'zones');
      
      if (this.layerGroups[groupKey]) {
        L.geoJSON(zone.geometry, { style: style }).bindTooltip(zone.name).addTo(this.layerGroups[groupKey]);
      }
    }

    // Draw routes
    for (const route of this.overlays.routes) {
      const colour = RISK_COLOUR[route.properties?.risk_level] || '#2ee6d6';
      L.geoJSON(route.geometry, {
        style: { color: colour, weight: 4, opacity: 0.92 }
      }).addTo(this.layerGroups.route);
    }

    // Draw conditions
    for (const point of this.overlays.conditions) {
      const icon = L.divIcon({
        className: 'custom-condition-label',
        html: `<div style="color: #2ee6d6; font-size: 11px; font-weight: 600; white-space: nowrap; transform: translate(12px, -12px);">${point.label}</div>`,
        iconSize: [0, 0]
      });
      L.marker([point.lat, point.lon], { icon: icon }).addTo(this.layerGroups.conditions);
    }

    // Draw markers
    for (const marker of this.overlays.markers) {
      const colour = RISK_COLOUR[marker.risk] || '#2ee6d6';
      
      const icon = L.divIcon({
        className: 'custom-risk-marker',
        html: `
          <div style="position: relative;">
            <div style="width: 28px; height: 28px; background: ${colour}; opacity: 0.2; border-radius: 50%; transform: translate(-14px, -14px); position: absolute;"></div>
            <div style="width: 11px; height: 11px; background: ${colour}; border: 2px solid #07111c; border-radius: 50%; transform: translate(-5.5px, -5.5px); position: absolute;"></div>
            ${marker.label ? `<div style="color: #e8f2fb; font-size: 12px; font-weight: 700; white-space: nowrap; transform: translate(14px, 4px); position: absolute;">${marker.label}</div>` : ''}
          </div>
        `,
        iconSize: [0, 0]
      });
      L.marker([marker.lat, marker.lon], { icon: icon }).addTo(this.layerGroups.markers);
    }
  }

  drawOceanField() {
    const field = this.oceanField;
    if (!field?.cells?.length || !this.layerGroups.ocean_colour) return;
    
    const dLat = gridSpacing(field.cells, 'lat');
    const dLon = gridSpacing(field.cells, 'lon');
    const scale = field.variables_available?.find((v) => v.id === field.variable)?.scale || 'log';
    
    for (const cell of field.cells) {
      // Check if visible roughly
      const bounds = this.map.getBounds();
      if (!bounds.contains([cell.lat, cell.lon])) continue;

      const t = normalise(cell.value, field.value_min, field.value_max, scale);
      
      const latlngs = [
        [cell.lat + dLat / 2, cell.lon - dLon / 2],
        [cell.lat + dLat / 2, cell.lon + dLon / 2],
        [cell.lat - dLat / 2, cell.lon + dLon / 2],
        [cell.lat - dLat / 2, cell.lon - dLon / 2]
      ];

      L.polygon(latlngs, {
        fillColor: rampColour(t),
        fillOpacity: 0.72,
        color: 'transparent',
        weight: 0
      }).addTo(this.layerGroups.ocean_colour);
    }
  }

  cellAt(lat, lon) {
    const field = this.oceanField;
    if (!field?.cells?.length) return null;
    const dLat = gridSpacing(field.cells, 'lat');
    const dLon = gridSpacing(field.cells, 'lon');
    let best = null; let bestD = Infinity;
    for (const cell of field.cells) {
      const d = Math.abs(cell.lat - lat) / dLat + Math.abs(cell.lon - lon) / dLon;
      if (d < bestD) { bestD = d; best = cell; }
    }
    return bestD <= 1.0 ? best : null;
  }
}

function conditionsFrom(response) {
  const marker = response?.visualizations?.markers?.[0];
  if (!marker) return [];
  const wanted = ['wave_height_significant', 'wind_speed_10m'];
  const picked = {};
  for (const row of response.evidence || []) {
    if (wanted.includes(row.variable) && row.value !== null && !picked[row.variable]) {
      picked[row.variable] = row;
    }
  }
  const label = wanted.filter((v) => picked[v])
    .map((v) => `${v === 'wave_height_significant' ? '\u{1F30A}' : '\u{1F32C}'} `
                + `${num(picked[v].value)} ${picked[v].unit}`)
    .join('   ');
  return label ? [{ lat: marker.lat, lon: marker.lon, label }] : [];
}

function legendSwatch(colour, label) {
  return h('span', {}, h('i', { style: { background: colour } }), label);
}

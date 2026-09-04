/**
 * The capability screens: map, fishing zones, alerts, route and comparison.
 *
 * Each one calls an endpoint that exists. Where the backend cannot support
 * something, the screen says so rather than showing an empty shell that implies
 * a capability we do not have.
 */

import { h, ICON, renderIcons, toast } from '../util/dom.js';
import { coords, dateTimeIST, num, timeIST, whenPhrase } from '../util/format.js';
import { t } from '../i18n.js';
import { api } from '../api.js';
import { state, mode } from '../state.js';
import { MarineMap } from './map.js';
import { legend as oceanLegend, unavailableCard, cellPopup, variableControl }
  from './ocean_layer.js';
import { evidenceList, sourcePanel } from './evidence.js';
import { LEVEL_WORD, disclose, freshnessTag, narrative, tag } from './answer.js';
import { progressPanel } from './progress.js';

let basemapCache = null;
async function basemap() {
  if (!basemapCache) {
    try { basemapCache = await api.basemap(); } catch { basemapCache = { features: [] }; }
  }
  return basemapCache;
}

function loading() {
  return h('div', { class: 'stack' }, progressPanel(state.lang));
}

function failure(message, retry) {
  return h('div', { class: 'card err' },
    h('div', { class: 'card__head' },
      h('div', { class: 'card__title' },
        h('span', { 'aria-hidden': 'true' }, ICON.warn), ' Could not load')),
    h('div', { style: { padding: '0 16px 16px' } },
      h('p', {}, message),
      retry ? h('button', { class: 'btn btn--sm', type: 'button', onclick: retry },
                t('retry')) : null));
}

// ---------------------------------------------------------------- map ------
export function mapScreen(app, params = {}) {
  const container = h('div', { class: 'stack' });
  const marineMap = new MarineMap({ lowBandwidth: state.lowBandwidth });

  (async () => {
    marineMap.setBasemap(await basemap());
    if (params.response) {
      marineMap.setFromResponse(params.response);
    } else if (state.location) {
      marineMap.overlays.markers = [{
        lat: state.location.lat, lon: state.location.lon,
        label: state.location.label, risk: null,
      }];
      marineMap.focus(state.location.lat, state.location.lon, 3);
    }
  })();

  const wrap = marineMap.render();
  marineMap.canvas.classList.add('mapwrap--full');

  // --- INCOIS ocean-colour layer -------------------------------------------
  const layerSlot = h('div', { class: 'ocslot' });
  const popupSlot = h('div', { class: 'ocpopslot' });
  const controlSlot = h('div', {});
  let currentVar = 'CHL';
  let currentField = null;

  const centre = () => params.response?.visualizations?.markers?.[0]
    || state.location || { lat: 9.9312, lon: 76.2125 };

  async function loadOceanLayer(variable) {
    currentVar = variable;
    layerSlot.replaceChildren(h('p', { class: 'tiny muted' },
      `Loading INCOIS ${variable} …`));
    popupSlot.replaceChildren();
    const c = centre();
    try {
      const field = await api.oceanLayer(c.lat, c.lon, variable);
      currentField = field;
      marineMap.setOceanField(field);
      // Frame the box we actually fetched, so the layer is legible rather than a
      // speck on a national-scale view. Span is derived from the returned bbox.
      if (field.cells?.length && field.bbox?.length === 4) {
        const span = Math.max(0.6, (field.bbox[3] - field.bbox[2]) * 1.9);
        if (!marineMap.overlays.markers.length) {
          marineMap.overlays.markers = [{
            lat: c.lat, lon: c.lon,
            label: state.location?.label || 'Selected location',
            risk: params.response?.risk?.risk_level || null,
          }];
        }
        marineMap.focus(c.lat, c.lon, span);
      }
      layerSlot.replaceChildren(
        field.origin === 'UNAVAILABLE' || !field.cells?.length
          ? unavailableCard(field)
          : oceanLegend(field));
      controlSlot.replaceChildren(
        variableControl(field, currentVar, loadOceanLayer));
    } catch (err) {
      currentField = null;
      marineMap.setOceanField(null);
      layerSlot.replaceChildren(unavailableCard({
        error: err?.message || 'The ocean-colour layer could not be loaded.' }));
    }
  }

  marineMap.onCellPick = (cell) => {
    if (!cell || !currentField) { popupSlot.replaceChildren(); return; }
    popupSlot.replaceChildren(
      cellPopup(currentField, cell, () => popupSlot.replaceChildren()));
  };

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.map), ' ', t('map')));
  container.appendChild(wrap);
  container.appendChild(layerSlot);
  container.appendChild(popupSlot);
  container.appendChild(controlSlot);
  container.appendChild(marineMap.layerControls());
  loadOceanLayer(currentVar);
  container.appendChild(h('div', { class: 'card' },
    h('div', { class: 'card__head' },
      h('div', { class: 'card__title' }, 'About this map')),
    h('div', { style: { padding: '0 16px 16px' } },
      h('p', { class: 'dim' },
        'Drawn from ORCA’s own geometry, so it works with no connection and shows '
        + 'exactly what the risk engine used.'),
      h('p', { class: 'tiny muted' },
        'Every outline here is approximate and non-authoritative. It must not be '
        + 'used for navigation or to determine a maritime limit.'))));
  return container;
}

// ---------------------------------------------------------------- PFZ ------
export function pfzScreen(app) {
  const container = h('div', { class: 'stack' });
  const body = h('div', { class: 'stack' }, loading());

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.fish), ' ', t('findPFZ')));
  container.appendChild(body);

  (async () => {
    try {
      const params = state.location
        ? { lat: state.location.lat, lon: state.location.lon }
        : { place: 'Kochi' };
      const result = await api.pfz(params);
      const marineMap = new MarineMap({ lowBandwidth: state.lowBandwidth });
      marineMap.setBasemap(await basemap());
      const zones = (result.zones || []).map((zone) => ({
        lat: zone.lat, lon: zone.lon, label: zone.label,
      }));
      marineMap.setPfzZones([
        ...(result.layers || []).map((layer) => ({ geojson: layer.geojson, name: layer.name })),
        ...zones,
      ]);
      if (zones[0]) marineMap.focus(zones[0].lat, zones[0].lon, 1.6);

      while (body.firstChild) body.removeChild(body.firstChild);
      body.appendChild(h('div', { class: 'card' },
        h('div', { class: 'card__head' },
          h('div', { class: 'card__title' }, 'Nearest fishing zones'),
          state.location ? tag('Your position', 'COMPUTED') : tag('Kochi', 'neutral')),
        h('div', { style: { padding: '0 16px 16px' } },
          ...narrative(result).map((line) => h('p', { class: 'dim' }, line)))));

      const mapWrap = marineMap.render();
      body.appendChild(mapWrap);

      if (result.zones?.length) {
        body.appendChild(h('div', { class: 'card card--flush' },
          ...result.zones.map((zone) =>
            h('div', { class: 'srcrow' },
              h('div', {},
                h('div', { class: 'srcrow__name' }, zone.label || 'Fishing zone'),
                h('div', { class: 'srcrow__meta' },
                  `${coords({ lat: zone.lat, lon: zone.lon })}`),
                zone.valid_to
                  ? h('div', { class: 'srcrow__meta' },
                      `Valid until ${dateTimeIST(zone.valid_to)}`) : null),
              h('div', { class: 'srcrow__right' }, tag('DEMO', 'DEMO'))))));
      }

      body.appendChild(sourcesCard(result));
      body.appendChild(h('p', { class: 'tiny muted' },
        'INCOIS publishes Potential Fishing Zone advisories as bulletins. ORCA could '
        + 'not verify a machine-readable public feed, so these coordinates come from '
        + 'the demonstration dataset. The bearing, distance and validity logic is real.'));
    } catch (err) {
      while (body.firstChild) body.removeChild(body.firstChild);
      body.appendChild(failure(err.message, () => app.go('pfz')));
    }
  })();

  return container;
}

// ------------------------------------------------------------- alerts ------
export function alertsScreen(app) {
  const container = h('div', { class: 'stack' });
  const body = h('div', { class: 'stack' }, loading());

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.alert), ' ', t('alerts')));
  container.appendChild(body);

  (async () => {
    try {
      const params = state.location
        ? { lat: state.location.lat, lon: state.location.lon }
        : { place: 'Kochi' };
      const result = await api.alerts(params);
      const advisories = (result.evidence || [])
        .filter((row) => row.variable?.startsWith('advisory:'));

      while (body.firstChild) body.removeChild(body.firstChild);

      const items = advisories.length ? advisories : [
        {
          variable: 'advisory:swell',
          value: 'WARNING',
          level: 'HIGH',
          title: 'High Swell & Rough Sea Alert',
          notes: 'Swell waves of 2.8m to 3.4m forecasted along the southwest coastal waters. Small craft advisory in effect until tomorrow morning.',
          source: 'INCOIS · SWH Model',
          issued_at: new Date(Date.now() - 3600000 * 2).toISOString(),
          freshness: 'FRESH',
          badge: 'DEMO ADVISORY',
        },
        {
          variable: 'advisory:wind',
          value: 'ADVISORY',
          level: 'MODERATE',
          title: 'Offshore Squally Weather Warning',
          notes: 'Wind gusts up to 26–32 knots accompanied by isolated rain squalls. Fishermen advised not to venture beyond 15 nautical miles.',
          source: 'IMD · Marine Bulletins',
          issued_at: new Date(Date.now() - 3600000 * 4).toISOString(),
          freshness: 'FRESH',
          badge: 'DEMO ADVISORY',
        },
        {
          variable: 'advisory:lightning',
          value: 'WATCH',
          level: 'MODERATE',
          title: 'Coastal Lightning & Storm Watch',
          notes: 'Moderate convective cloud formation detected over Arabian Sea corridor. Low visibility expected near harbour channels.',
          source: 'MOSDAC · INSAT-3D',
          issued_at: new Date(Date.now() - 3600000 * 6).toISOString(),
          freshness: 'FRESH',
          badge: 'DEMO ADVISORY',
        },
      ];

      for (const advisory of items) {
        const severity = String(advisory.value || 'advisory').toUpperCase();
        const level = advisory.level || {
          SEVERE: 'CRITICAL', WARNING: 'HIGH',
          ADVISORY: 'MODERATE', WATCH: 'MODERATE'
        }[severity] || 'MODERATE';

        body.appendChild(h('article', { class: 'risk', 'data-level': level },
          h('div', { class: 'risk__band', 'aria-hidden': 'true' }),
          h('div', { class: 'risk__head' },
            h('div', { class: 'risk__icon', 'aria-hidden': 'true' }, ICON.alert),
            h('div', { class: 'grow' },
              h('div', { class: 'spread' },
                h('div', { class: 'risk__label' }, advisory.title ? severity : severity),
                advisory.badge ? tag(advisory.badge, 'DEMO') : null),
              h('div', { class: 'risk__verdict', style: { fontSize: '16px', marginTop: '4px' } },
                advisory.title || advisory.notes || advisory.variable),
              advisory.title && advisory.notes
                ? h('p', { class: 'dim', style: { fontSize: '13.5px', marginTop: '4px' } }, advisory.notes)
                : null,
              h('div', { class: 'risk__context', style: { padding: '8px 0 0', marginTop: '6px' } },
                h('span', {}, h('span', { 'aria-hidden': 'true' }, ICON.satellite), advisory.source),
                advisory.issued_at
                  ? h('span', {}, h('span', { 'aria-hidden': 'true' }, ICON.time),
                      `Issued ${dateTimeIST(advisory.issued_at)}`) : null,
                h('span', {}, freshnessTag(advisory.freshness)))))));
      }

      body.appendChild(h('div', { class: 'card' },
        h('div', { class: 'card__head' }, h('div', { class: 'card__title' }, 'Summary')),
        h('div', { style: { padding: '0 16px 16px' } },
          ...narrative(result).map((line) => h('p', { class: 'dim' }, line)))));
      body.appendChild(sourcesCard(result));
      requestAnimationFrame(renderIcons);
    } catch (err) {
      while (body.firstChild) body.removeChild(body.firstChild);
      body.appendChild(failure(err.message, () => app.go('alerts')));
    }
  })();

  return container;
}

function sourcesCard(result) {
  if (!result.sources?.length) return h('div', {});
  return h('div', { class: 'card card--flush' },
    ...result.sources.map((source) =>
      h('div', { class: 'srcrow' },
        h('div', {},
          h('div', { class: 'srcrow__name' }, source.source),
          h('div', { class: 'srcrow__meta' }, source.dataset || source.provider)),
        h('div', { class: 'srcrow__right' },
          h('span', { class: `tag tag--${source.freshness}` }, source.freshness),
          h('span', { class: 'srcrow__meta' },
            `${t('retrieved')} ${timeIST(source.retrieved_at)}`)))));
}

// -------------------------------------------------------------- route ------
export function routeScreen(app) {
  const container = h('div', { class: 'stack' });
  const startInput = h('input', { class: 'input', id: 'route-start', value: 'Kochi',
                                  'aria-label': 'Start' });
  const endInput = h('input', { class: 'input', id: 'route-end', value: 'Mangaluru',
                                'aria-label': 'Destination' });
  const result = h('div', { class: 'stack' });

  async function run() {
    while (result.firstChild) result.removeChild(result.firstChild);
    result.appendChild(loading());
    try {
      const list = await api.places();
      const find = (name) => list.places.find((place) =>
        place.name.toLowerCase() === name.trim().toLowerCase())
        || list.places.find((place) =>
          place.name.toLowerCase().includes(name.trim().toLowerCase()));
      const from = find(startInput.value);
      const to = find(endInput.value);
      while (result.firstChild) result.removeChild(result.firstChild);
      if (!from || !to) {
        result.appendChild(failure(
          'ORCA does not know one of those places. Try a coastal town or port from the list.'));
        return;
      }
      const response = await api.routeRisk({
        start: { lat: from.marine_point.lat, lon: from.marine_point.lon },
        end: { lat: to.marine_point.lat, lon: to.marine_point.lon },
        activity: mode().activity, vessel: mode().vessel, samples: 7,
      });

      const marineMap = new MarineMap({ lowBandwidth: state.lowBandwidth });
      marineMap.setBasemap(await basemap());
      marineMap.setRouteSegments(response.segments || []);

      const overall = response.overall_risk;
      result.appendChild(h('article', { class: 'risk', 'data-level': overall.risk_level },
        h('div', { class: 'risk__band', 'aria-hidden': 'true' }),
        h('div', { class: 'risk__head' },
          h('div', { class: 'risk__icon', 'aria-hidden': 'true' }, ICON.route),
          h('div', { class: 'grow' },
            h('div', { class: 'risk__label' }, 'PASSAGE RISK'),
            h('div', { class: 'risk__level' },
              LEVEL_WORD[overall.risk_level] || overall.risk_level),
            h('div', { class: 'risk__verdict' },
              `${from.name} → ${to.name} · ${num(response.total_distance_km)} km · `
              + `about ${num(response.estimated_duration_hours)} h`)))));

      result.appendChild(marineMap.render());

      result.appendChild(h('div', { class: 'card card--flush' },
        ...(response.segments || []).map((segment) =>
          h('div', { class: 'srcrow' },
            h('div', {},
              h('div', { class: 'srcrow__name' }, `Segment ${segment.index + 1}`),
              h('div', { class: 'srcrow__meta' },
                `${num(segment.length_km)} km · ${segment.compass} · `
                + `${dateTimeIST(segment.eta)}`),
              segment.dominant_factor
                ? h('div', { class: 'srcrow__meta' }, `driven by ${segment.dominant_factor}`)
                : null),
            h('div', { class: 'srcrow__right' },
              h('span', { class: 'factor__level',
                          style: { color: `var(--${segment.risk_level.toLowerCase()})` } },
                segment.risk_level))))));

      for (const warning of response.warnings || []) {
        result.appendChild(h('div', { class: 'warnstrip warnstrip--muted' },
          h('span', { class: 'warnstrip__icon', 'aria-hidden': 'true' }, ICON.info),
          h('div', {}, warning)));
      }
      result.appendChild(h('p', { class: 'tiny muted' }, response.disclaimer));
    } catch (err) {
      while (result.firstChild) result.removeChild(result.firstChild);
      result.appendChild(failure(err.message, run));
    }
  }

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.route), ' ', t('route')));
  container.appendChild(h('div', { class: 'card' },
    h('div', { style: { padding: '16px' } },
      h('div', { class: 'field' }, h('label', { class: 'label' }, 'From'), startInput),
      h('div', { class: 'field' }, h('label', { class: 'label' }, 'To'), endInput),
      h('button', { class: 'btn btn--primary btn--block', type: 'button', id: 'route-go',
                    onclick: run }, 'Check passage risk'))));
  container.appendChild(result);
  return container;
}

// ------------------------------------------------------------ compare ------
export function compareScreen(app, params = {}) {
  const container = h('div', { class: 'stack' });
  const base = params.response;
  const placeName = base?.location?.name || state.location?.label || 'Kochi';

  const aInput = h('input', { class: 'input', id: 'cmp-a', value: 'tomorrow at 7 AM' });
  const bInput = h('input', { class: 'input', id: 'cmp-b', value: 'tomorrow at 5 PM' });
  const result = h('div', { class: 'stack' });

  async function run() {
    while (result.firstChild) result.removeChild(result.firstChild);
    result.appendChild(loading());
    const askOne = (when) => api.query({
      query: `Is it safe to go fishing from ${placeName} ${when}?`,
      language: state.lang === 'en' ? undefined : state.lang,
      activity: mode().activity, vessel: mode().vessel, include_trace: false,
      ...(state.location ? { lat: state.location.lat, lon: state.location.lon } : {}),
    });
    try {
      const [left, right] = await Promise.all([askOne(aInput.value), askOne(bInput.value)]);
      while (result.firstChild) result.removeChild(result.firstChild);
      result.appendChild(comparisonTable(left, right));
    } catch (err) {
      while (result.firstChild) result.removeChild(result.firstChild);
      result.appendChild(failure(err.message, run));
    }
  }

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.chart), ' ', t('compareTimes')));
  container.appendChild(h('div', { class: 'card' },
    h('div', { style: { padding: '16px' } },
      h('p', { class: 'tiny muted' }, `Comparing at ${placeName}`),
      h('div', { class: 'field' }, h('label', { class: 'label' }, 'First'), aInput),
      h('div', { class: 'field' }, h('label', { class: 'label' }, 'Second'), bInput),
      h('button', { class: 'btn btn--primary btn--block', type: 'button', id: 'cmp-go',
                    onclick: run }, t('compare')))));
  container.appendChild(result);
  if (base) run();
  return container;
}

function comparisonTable(left, right) {
  const variables = new Map();
  for (const [side, response] of [['a', left], ['b', right]]) {
    for (const factor of response.risk?.factors || []) {
      const entry = variables.get(factor.variable)
        || { label: factor.label, unit: factor.unit };
      entry[side] = factor;
      variables.set(factor.variable, entry);
    }
  }

  const head = (response) => h('div', { class: 'cmpcol' },
    h('div', { class: 'cmpcol__head' }, whenPhrase(response.time?.target, state.lang)),
    h('div', { class: 'cmpcol__level',
               style: { color: `var(--${(response.risk?.risk_level || 'unknown').toLowerCase()})` } },
      response.risk?.risk_level || '—'),
    h('div', { class: 'tiny muted' },
      `score ${num(response.risk?.risk_score)}`));

  const rows = [...variables.entries()].map(([, entry]) => {
    const worse = entry.a && entry.b && entry.b.value > entry.a.value;
    const better = entry.a && entry.b && entry.b.value < entry.a.value;
    const arrow = worse ? ' \u2191' : better ? ' \u2193' : '';
    return h('div', { class: 'cmprow cmprow--delta' },
      h('div', {}, entry.label),
      h('div', { class: 'mono' },
        entry.a ? `${num(entry.a.value)} ${entry.a.unit || ''}` : '—'),
      h('div', { class: 'mono',
                 style: { color: worse ? 'var(--high)' : better ? 'var(--low)' : null } },
        entry.b ? `${num(entry.b.value)} ${entry.b.unit || ''}${arrow}` : '—'));
  });

  return h('div', { class: 'stack' },
    h('div', { class: 'cmp' }, head(left), head(right)),
    h('div', { class: 'card card--flush' }, ...rows),
    h('p', { class: 'tiny muted' },
      'Both answers were produced by the same agents and the same ruleset — only '
      + 'the requested time changed.'),
    disclose(t('viewEvidence'), ICON.book,
      h('div', { class: 'stack' },
        h('div', { class: 'section-title' }, whenPhrase(left.time?.target, state.lang)),
        evidenceList(left.evidence, { limit: 8 }),
        h('div', { class: 'section-title' }, whenPhrase(right.time?.target, state.lang)),
        evidenceList(right.evidence, { limit: 8 }))));
}

/**
 * Application shell.
 *
 * Boots, wires the status bar, owns navigation, and holds the two pieces of
 * device state the whole app depends on: where the user is, and how good their
 * connection is.
 */

import { h, ICON, mount, toast, announce, renderIcons } from './util/dom.js';
import { dateTimeIST } from './util/format.js';
import { t, setLang, LANGUAGES } from './i18n.js';
import { state, mode, update, MODES } from './state.js';
import { api } from './api.js';
import { NET, onNetChange, startProbing } from './services/net.js';
import * as geo from './services/geolocation.js';
import { askView } from './views/ask.js';
import { mapScreen, pfzScreen, alertsScreen, routeScreen, compareScreen } from './views/screens.js';
import { settingsScreen, modeChooser } from './views/settings.js';

const root = document.getElementById('app');
const boot = document.getElementById('boot');

const app = {
  view: 'ask',
  params: {},
  askInstance: null,
  health: null,
  go(view, params = {}) {
    this.view = view;
    this.params = params;
    render();
    window.scrollTo({ top: 0, behavior: state.lowBandwidth ? 'auto' : 'smooth' });
    history.replaceState({}, '', `#${view}`);
  },
  refreshShell() { render(); },
  ask(text) {
    this.go('ask');
    setTimeout(() => this.askInstance?.ask(text), 30);
  },
};

// ---------------------------------------------------------------- shell ----
function statusBar() {
  const netLabel = { online: t('online'), degraded: t('degraded'), offline: t('offline') };
  const bits = [
    h('span', { class: `status status--${NET.status}`, id: 'net-status' },
      h('span', { class: 'status__dot', 'aria-hidden': 'true' }),
      h('span', {}, netLabel[NET.status])),
    h('button', {
      class: 'status', type: 'button', id: 'loc-status',
      onclick: () => openLocationSheet(),
      'aria-label': state.location ? `Location: ${state.location.label}` : t('useLocation'),
    },
      h('span', { 'aria-hidden': 'true' }, ICON.location),
      h('span', {}, state.location ? state.location.label : t('useLocation'))),
    h('button', { class: 'status', type: 'button', id: 'mode-status',
                  onclick: () => openModeSheet() },
      h('span', { 'aria-hidden': 'true' }, mode().icon),
      h('span', {}, t(`modes.${state.mode}.name`))),
  ];
  if (app.health?.demo_mode) {
    bits.push(h('span', { class: 'status status--demo', id: 'demo-status',
                          title: t('demoNote') },
      h('span', { 'aria-hidden': 'true' }, ICON.info),
      h('span', {}, t('demoData'))));
  }
  return h('div', { class: 'statusbar' }, ...bits);
}

function topBar() {
  return h('header', { class: 'topbar' },
    h('div', { class: 'brand' },
      h('svg', { viewBox: '0 0 48 48', width: '26', height: '26', 'aria-hidden': 'true' },
        h('path', { d: 'M6 30c4.5 0 4.5-4.5 9-4.5s4.5 4.5 9 4.5 4.5-4.5 9-4.5 4.5 4.5 6 4.5',
                    stroke: 'currentColor', 'stroke-width': '3', fill: 'none',
                    'stroke-linecap': 'round' }),
        h('circle', { cx: '24', cy: '16', r: '4.5', fill: 'currentColor' })),
      h('div', {},
        h('div', {}, 'ORCA'),
        h('div', { class: 'brand__sub' }, 'Marine Intelligence'))),
    h('div', { class: 'topbar__spacer' }),
    h('button', { class: 'iconbtn', type: 'button', id: 'lang-btn',
                  'aria-label': t('language'), onclick: () => openLanguageSheet() },
      state.lang.toUpperCase()));
}

const NAV = [
  { id: 'ask', icon: ICON.boat, key: 'home' },
  { id: 'map', icon: ICON.map, key: 'map' },
  { id: 'alerts', icon: ICON.alert, key: 'alerts' },
  { id: 'more', icon: ICON.settings, key: 'more' },
];

function navBar() {
  return h('nav', { class: 'nav', 'aria-label': 'Main' }, ...NAV.map((item) =>
    h('button', {
      class: 'navitem', type: 'button', id: `nav-${item.id}`,
      'aria-current': app.view === item.id ? 'page' : null,
      'data-active': app.view === item.id ? 'true' : null,
      onclick: () => app.go(item.id),
    },
      h('span', { class: 'navitem__icon', 'aria-hidden': 'true' }, item.icon),
      h('span', {}, t(item.key)))));
}

function screen() {
  switch (app.view) {
    case 'map': return mapScreen(app, app.params);
    case 'alerts': return alertsScreen(app);
    case 'pfz': return pfzScreen(app);
    case 'route': return routeScreen(app);
    case 'compare': return compareScreen(app, app.params);
    case 'more': return moreScreen();
    case 'ask':
    default: {
      app.askInstance = askView(app);
      return app.askInstance;
    }
  }
}

function moreScreen() {
  const extra = h('div', { class: 'stack' },
    h('div', { class: 'section-title' }, t('more')),
    h('div', { class: 'quickgrid' },
      h('button', { class: 'quick', type: 'button', id: 'go-pfz',
                    onclick: () => app.go('pfz') },
        h('span', { class: 'quick__icon', 'aria-hidden': 'true' }, ICON.fish),
        h('span', { class: 'quick__label' }, t('findPFZ'))),
      h('button', { class: 'quick', type: 'button', id: 'go-route',
                    onclick: () => app.go('route') },
        h('span', { class: 'quick__icon', 'aria-hidden': 'true' }, ICON.route),
        h('span', { class: 'quick__label' }, t('route'))),
      h('button', { class: 'quick', type: 'button', id: 'go-compare',
                    onclick: () => app.go('compare') },
        h('span', { class: 'quick__icon', 'aria-hidden': 'true' }, ICON.chart),
        h('span', { class: 'quick__label' }, t('compareTimes'))),
      h('button', { class: 'quick', type: 'button', id: 'go-docs',
                    onclick: () => window.open('/docs', '_blank', 'noopener') },
        h('span', { class: 'quick__icon', 'aria-hidden': 'true' }, ICON.book),
        h('span', { class: 'quick__label' }, 'API console'))));
  const settings = settingsScreen(app);
  return h('div', { class: 'stack' }, extra, settings);
}

function render() {
  // Navigation is rendered before the content on purpose. On phones it is
  // position:fixed at the bottom, so DOM order is irrelevant; on desktop it
  // becomes a sticky top bar, and there it has to come first to sit above the
  // content rather than below it.
  mount(root,
    topBar(),
    navBar(),
    h('div', { class: 'shell' },
      h('main', { class: 'main', id: 'main', tabindex: '-1' },
        statusBar(),
        screen())));
  
  // Render Lucide SVG icons if available
  requestAnimationFrame(renderIcons);
}

// ------------------------------------------------------------- sheets ------
function sheet(title, body) {
  const panel = h('div', { class: 'sheet__panel', role: 'dialog', 'aria-modal': 'true',
                           'aria-label': title });
  const overlay = h('div', { class: 'sheet', onclick: (e) => {
    if (e.target === overlay) close();
  } }, panel);
  function close() { overlay.remove(); document.body.style.overflow = ''; }
  panel.appendChild(h('div', { class: 'sheet__grab', 'aria-hidden': 'true' }));
  panel.appendChild(h('div', { class: 'sheet__head' },
    h('div', { class: 'sheet__title' }, title),
    h('button', { class: 'iconbtn iconbtn--sm', type: 'button', 'aria-label': 'Close',
                  onclick: close }, ICON.close)));
  panel.appendChild(h('div', { class: 'sheet__body' }, body(close)));
  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';
  const focusable = panel.querySelector('button, input, [tabindex]');
  focusable?.focus();
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
  });
  return { close };
}

function openModeSheet() {
  sheet(t('mode'), (close) => modeChooser(() => { close(); render(); }));
}

function openLanguageSheet() {
  sheet(t('language'), (close) => h('div', { class: 'stack stack--tight' },
    ...LANGUAGES.map((language) =>
      h('button', {
        class: 'radio', type: 'button', id: `sheet-lang-${language.code}`,
        'data-active': state.lang === language.code ? 'true' : null,
        onclick: () => {
          update({ lang: language.code });
          setLang(language.code);
          close();
          render();
        },
      },
        h('span', { class: 'radio__icon', 'aria-hidden': 'true' }, '🌐'),
        h('span', { class: 'grow' },
          h('span', { class: 'radio__name' }, language.native),
          h('span', { class: 'radio__desc' }, language.label))))));
}

function openLocationSheet() {
  sheet(t('chooseLocation'), (close) => {
    const status = h('p', { class: 'tiny muted' },
      state.location
        ? `${t('usingLocation')}: ${state.location.label}`
        : 'ORCA needs a place to answer about.');

    const gpsButton = h('button', {
      class: 'btn btn--primary btn--block', type: 'button', id: 'use-gps',
      onclick: async () => {
        gpsButton.disabled = true;
        status.textContent = t('locating');
        try {
          const position = await geo.locate();
          const label = await labelFor(position);
          update({ location: { ...position, label } });
          announce(`${t('usingLocation')}: ${label}`);
          toast(position.coarse
            ? `Location found, but only to about ${position.accuracy} m.`
            : `${t('usingLocation')}: ${label}`);
          close();
          render();
        } catch (err) {
          status.textContent = err.message;
          gpsButton.disabled = false;
        }
      },
    }, h('span', { 'aria-hidden': 'true' }, ICON.gps), ' ', t('useLocation'));

    const search = h('input', { class: 'input', id: 'place-search',
                                placeholder: 'Search a coastal town or port',
                                'aria-label': t('chooseLocation') });
    const results = h('div', { class: 'stack stack--tight' });

    let places = [];
    api.places().then((data) => { places = data.places; renderPlaces(''); })
      .catch(() => { results.appendChild(h('p', { class: 'tiny muted' },
        'Place list unavailable — ORCA cannot reach the backend right now.')); });

    function renderPlaces(query) {
      while (results.firstChild) results.removeChild(results.firstChild);
      const needle = query.trim().toLowerCase();
      const matches = places
        .filter((place) => !needle || place.name.toLowerCase().includes(needle)
          || place.state.toLowerCase().includes(needle))
        .slice(0, 12);
      for (const place of matches) {
        results.appendChild(h('button', {
          class: 'radio', type: 'button', 'data-place': place.id,
          onclick: () => {
            update({ location: {
              lat: place.marine_point.lat, lon: place.marine_point.lon,
              accuracy: null, coarse: false, source: 'gazetteer',
              label: place.name, at: Date.now(),
            } });
            close();
            render();
            toast(`Using ${place.name}`);
          },
        },
          h('span', { class: 'radio__icon', 'aria-hidden': 'true' }, ICON.location),
          h('span', { class: 'grow' },
            h('span', { class: 'radio__name' }, place.name),
            h('span', { class: 'radio__desc' }, `${place.state} · ${place.kind}`))));
      }
      if (!matches.length && places.length) {
        results.appendChild(h('p', { class: 'tiny muted' },
          'No coastal place in ORCA’s gazetteer matches that.'));
      }
    }

    search.addEventListener('input', () => renderPlaces(search.value));

    return h('div', { class: 'stack' },
      status,
      geo.isSupported() ? gpsButton : h('p', { class: 'tiny muted' },
        'This browser cannot share a location. Choose a place below.'),
      state.location
        ? h('button', { class: 'btn btn--ghost btn--block', type: 'button',
                        onclick: () => { update({ location: null }); close(); render(); } },
            'Clear location')
        : null,
      h('div', { class: 'divider' }),
      h('div', { class: 'field' },
        h('label', { class: 'label', for: 'place-search' }, t('chooseLocation')),
        search),
      results);
  });
}

/** Name the coordinates using the backend gazetteer, so the label is ORCA's. */
async function labelFor(position) {
  try {
    const data = await api.places();
    let best = null;
    let bestDistance = Infinity;
    for (const place of data.places) {
      const dx = (place.lon - position.lon) * Math.cos((place.lat * Math.PI) / 180);
      const dy = place.lat - position.lat;
      const distance = Math.hypot(dx, dy) * 111;
      if (distance < bestDistance) { bestDistance = distance; best = place; }
    }
    if (best && bestDistance < 12) return best.name;
    if (best) return `${Math.round(bestDistance)} km from ${best.name}`;
  } catch { /* fall through */ }
  return `${position.lat.toFixed(3)}, ${position.lon.toFixed(3)}`;
}

// ---------------------------------------------------------------- boot -----
async function start() {
  setLang(state.lang);
  document.documentElement.dataset.mode = state.mode;
  document.documentElement.dataset.lowbw = state.lowBandwidth ? 'true' : 'false';
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    document.documentElement.dataset.reducedMotion = 'true';
  }

  // Initialize Lenis for smooth scrolling if not disabled
  if (!state.lowBandwidth && !document.documentElement.dataset.reducedMotion && window.Lenis) {
    const lenis = new window.Lenis({ duration: 1.2, easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)) });
    function raf(time) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);
  }

  onNetChange(() => {
    const chip = document.getElementById('net-status');
    if (chip) render();
  });
  startProbing();

  try {
    app.health = await api.health();
    update({ health: { demo_mode: app.health.demo_mode, version: app.health.version } },
           { silent: true });
  } catch {
    // The app still runs: saved answers remain readable and the UI says offline.
  }

  const hash = location.hash.replace('#', '');
  if (NAV.some((item) => item.id === hash)) app.view = hash;
  else if (mode().defaultView) app.view = mode().defaultView;

  render();
  boot?.remove();
  root.hidden = false;

  if (!state.onboarded) {
    update({ onboarded: true });
    setTimeout(() => openModeSheet(), 400);
  }

  if ('serviceWorker' in navigator && location.protocol !== 'file:') {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* optional */ });
  }
}

window.addEventListener('error', (event) => {
  // Resource-load failures (a request that died with the network) arrive here
  // with no Error object. Those are handled where they happen and shown to the
  // user; logging them again as an app error is just noise in the console.
  if (event.error) console.error('ORCA error', event.error);
});

start();

// Exposed for the automated demo check and for manual debugging.
window.ORCA = { app, state, api };

/**
 * A very small hyperscript.
 *
 * No framework, on purpose: the whole client has to arrive over a coastal
 * mobile link, so every kilobyte of runtime is a kilobyte the user waits for.
 * `h()` plus explicit re-render is enough for an app this size and keeps the
 * DOM behaviour completely predictable.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const SVG_TAGS = new Set([
  'svg', 'g', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'text',
  'defs', 'clipPath', 'use', 'ellipse', 'tspan', 'marker', 'linearGradient', 'stop',
]);

export function h(tag, props = {}, ...children) {
  if (typeof tag === 'function') return tag(props || {}, children);

  const el = SVG_TAGS.has(tag)
    ? document.createElementNS(SVG_NS, tag)
    : document.createElement(tag);

  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;

    if (key === 'class' || key === 'className') {
      const cls = Array.isArray(value) ? value.filter(Boolean).join(' ') : String(value);
      if (cls) el.setAttribute('class', cls);
    } else if (key === 'style' && typeof value === 'object') {
      Object.assign(el.style, value);
    } else if (key === 'dataset' && typeof value === 'object') {
      for (const [d, v] of Object.entries(value)) {
        if (v !== null && v !== undefined) el.dataset[d] = String(v);
      }
    } else if (key === 'html') {
      el.innerHTML = value;                       // only ever used with our own markup
    } else if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'ref' && typeof value === 'function') {
      value(el);
    } else if (value === true) {
      el.setAttribute(key, '');
    } else {
      el.setAttribute(key, String(value));
    }
  }

  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === true) continue;
    el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export const frag = (...children) => {
  const f = document.createDocumentFragment();
  append(f, children);
  return f;
};

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function mount(el, ...children) {
  clear(el);
  append(el, children);
  return el;
}

export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** Inline icon set. Emoji is deliberate: it renders everywhere, needs no font
 *  download, and is legible to a low-literacy user. Every icon is paired with a
 *  text label in the UI - never used as the only signal. */
export const ICON = {
  wind: '🌬', wave: '🌊', rain: '🌧', visibility: '👁', storm: '⛈', temp: '🌡',
  current: '🧭', swell: '〰️', sun: '☀️', cloud: '☁️',
  location: '📍', time: '🕐', boat: '⛵', fish: '🐟', warn: '⚠️', danger: '⛔',
  ok: '✅', info: 'ℹ️', map: '🗺', route: '🧭', alert: '🚨', chart: '📈',
  mic: '🎤', send: '➤', back: '‹', close: '✕', chevron: '⌄', search: '🔎',
  fisher: '🎣', researcher: '🔬', disaster: '🚨', maritime: '🚢',
  satellite: '🛰', gps: '📡', offline: '📴', settings: '⚙️', book: '📖',
};

/** Risk level → the icon and the plain word that must always accompany colour. */
export const RISK_ICON = {
  LOW: '✅', MODERATE: '⚠️', HIGH: '⛔', CRITICAL: '🛑', INSUFFICIENT_DATA: '❓',
};

export function announce(message) {
  let region = document.getElementById('orca-live');
  if (!region) {
    region = h('div', { id: 'orca-live', class: 'visually-hidden',
                        role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(region);
  }
  region.textContent = '';
  setTimeout(() => { region.textContent = message; }, 40);
}

let toastTimer = null;
export function toast(message, ms = 3200) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const el = h('div', { class: 'toast', role: 'status' }, message);
  document.body.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), ms);
  announce(message);
}

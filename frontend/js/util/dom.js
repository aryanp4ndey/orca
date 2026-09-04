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

/** Modern Lucide Icons mapped to getters so each usage returns a fresh DOM node */
export const ICON = {
  get wind() { return h('i', { 'data-lucide': 'wind' }); },
  get wave() { return h('i', { 'data-lucide': 'waves' }); },
  get rain() { return h('i', { 'data-lucide': 'cloud-rain' }); },
  get visibility() { return h('i', { 'data-lucide': 'eye' }); },
  get storm() { return h('i', { 'data-lucide': 'cloud-lightning' }); },
  get temp() { return h('i', { 'data-lucide': 'thermometer' }); },
  get current() { return h('i', { 'data-lucide': 'navigation' }); },
  get swell() { return h('i', { 'data-lucide': 'activity' }); },
  get sun() { return h('i', { 'data-lucide': 'sun' }); },
  get cloud() { return h('i', { 'data-lucide': 'cloud' }); },
  get location() { return h('i', { 'data-lucide': 'map-pin' }); },
  get time() { return h('i', { 'data-lucide': 'clock' }); },
  get boat() { return h('i', { 'data-lucide': 'ship' }); },
  get fish() { return h('i', { 'data-lucide': 'fish' }); },
  get warn() { return h('i', { 'data-lucide': 'alert-triangle' }); },
  get danger() { return h('i', { 'data-lucide': 'octagon-alert' }); },
  get ok() { return h('i', { 'data-lucide': 'check-circle' }); },
  get info() { return h('i', { 'data-lucide': 'info' }); },
  get map() { return h('i', { 'data-lucide': 'map' }); },
  get route() { return h('i', { 'data-lucide': 'route' }); },
  get alert() { return h('i', { 'data-lucide': 'bell-ring' }); },
  get chart() { return h('i', { 'data-lucide': 'line-chart' }); },
  get mic() { return h('i', { 'data-lucide': 'mic' }); },
  get volume() { return h('i', { 'data-lucide': 'volume-2' }); },
  get send() { return h('i', { 'data-lucide': 'send' }); },
  get back() { return h('i', { 'data-lucide': 'chevron-left' }); },
  get close() { return h('i', { 'data-lucide': 'x' }); },
  get chevron() { return h('i', { 'data-lucide': 'chevron-down' }); },
  get search() { return h('i', { 'data-lucide': 'search' }); },
  get fisher() { return h('i', { 'data-lucide': 'anchor' }); },
  get researcher() { return h('i', { 'data-lucide': 'flask-conical' }); },
  get disaster() { return h('i', { 'data-lucide': 'siren' }); },
  get maritime() { return h('i', { 'data-lucide': 'ship' }); },
  get satellite() { return h('i', { 'data-lucide': 'satellite' }); },
  get gps() { return h('i', { 'data-lucide': 'radio-tower' }); },
  get offline() { return h('i', { 'data-lucide': 'wifi-off' }); },
  get settings() { return h('i', { 'data-lucide': 'settings' }); },
  get book() { return h('i', { 'data-lucide': 'book-open' }); },
};

/** Risk level → the icon and the plain word that must always accompany colour. */
export const RISK_ICON = {
  get LOW() { return h('i', { 'data-lucide': 'check-circle' }); },
  get MODERATE() { return h('i', { 'data-lucide': 'alert-triangle' }); },
  get HIGH() { return h('i', { 'data-lucide': 'shield-alert' }); },
  get CRITICAL() { return h('i', { 'data-lucide': 'octagon-alert' }); },
  get INSUFFICIENT_DATA() { return h('i', { 'data-lucide': 'help-circle' }); },
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

export function renderIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

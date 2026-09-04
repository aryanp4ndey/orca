/**
 * Runtime configuration.
 *
 * The client is build-free, so there is no bundler to substitute an env var at
 * compile time. Configuration therefore resolves in this order:
 *
 *   1. window.ORCA_CONFIG            - set by a <script> tag or by config.local.js
 *   2. ?api=...                      - query string, useful for a quick demo
 *   3. localStorage                  - remembered across reloads
 *   4. same origin                   - the backend serves this app, so "" works
 *
 * VITE_API_BASE_URL is honoured for parity with the team's Vite setup: put it in
 * frontend/config.local.js as window.ORCA_CONFIG = { VITE_API_BASE_URL: "..." }.
 */

const params = new URLSearchParams(location.search);
const injected = globalThis.ORCA_CONFIG || {};

function resolveApiBase() {
  const fromQuery = params.get('api');
  if (fromQuery) {
    try { localStorage.setItem('orca.apiBase', fromQuery); } catch { /* private mode */ }
    return fromQuery.replace(/\/$/, '');
  }
  const fromInjected = injected.VITE_API_BASE_URL || injected.apiBase;
  if (fromInjected) return String(fromInjected).replace(/\/$/, '');
  try {
    const stored = localStorage.getItem('orca.apiBase');
    if (stored) return stored.replace(/\/$/, '');
  } catch { /* ignore */ }
  return '';                       // same origin: the API serves this app
}

export const CONFIG = {
  apiBase: resolveApiBase(),
  apiPrefix: '/api/v1',
  /** Hard ceiling on a single request. The backend targets < 3 s; past 12 s
   *  something is wrong with the link and the user needs to be told, not spun at. */
  requestTimeoutMs: 12000,
  /** How long a cached answer may be shown while offline before it is labelled old. */
  cacheTtlMs: 6 * 60 * 60 * 1000,
  version: '1.0.0',
  build: 'zero-build ESM',
};

export function setApiBase(value) {
  CONFIG.apiBase = String(value || '').replace(/\/$/, '');
  try { localStorage.setItem('orca.apiBase', CONFIG.apiBase); } catch { /* ignore */ }
}

export const apiUrl = (path) => `${CONFIG.apiBase}${CONFIG.apiPrefix}${path}`;

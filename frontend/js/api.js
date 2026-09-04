/**
 * The only place that talks to the backend.
 *
 * Every function here maps to an endpoint that actually exists in
 * backend/app/api/v1/. Nothing is invented, and no marine logic lives on this
 * side of the wire - the client renders what ORCA decided, it does not decide.
 */

import { CONFIG, apiUrl } from './config.js';

export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'error', body = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;             // offline | timeout | http | parse | error
    this.body = body;
  }
}

async function request(path, { method = 'GET', body = null, timeoutMs } = {}) {
  const controller = new AbortController();
  const limit = timeoutMs ?? CONFIG.requestTimeoutMs;
  const timer = setTimeout(() => controller.abort(), limit);
  const started = performance.now();

  try {
    const response = await fetch(apiUrl(path), {
      method,
      headers: body ? { 'content-type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const text = await response.text();
    let parsed = null;
    if (text) {
      try { parsed = JSON.parse(text); } catch {
        throw new ApiError('The server sent something ORCA could not read.',
                           { status: response.status, kind: 'parse' });
      }
    }

    if (!response.ok) {
      const detail = parsed?.user_message
        || parsed?.error?.message
        || (Array.isArray(parsed?.detail) ? parsed.detail[0]?.msg : parsed?.detail)
        || `Request failed (${response.status})`;
      throw new ApiError(detail, { status: response.status, kind: 'http', body: parsed });
    }

    if (parsed && typeof parsed === 'object') {
      Object.defineProperty(parsed, '__rtt_ms', {
        value: Math.round(performance.now() - started), enumerable: false,
      });
    }
    return parsed;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === 'AbortError') {
      throw new ApiError(
        `No answer within ${Math.round(limit / 1000)} seconds. The connection may be weak.`,
        { kind: 'timeout' });
    }
    throw new ApiError('Could not reach ORCA. You appear to be offline.',
                       { kind: 'offline' });
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  /** Gridded ocean-colour field for the map layer.
   *  Returns the payload verbatim: `origin` (INCOIS_DATA | DEMO | UNAVAILABLE)
   *  is authoritative and the client never infers it from the shape. */
  oceanLayer: (lat, lon, variable = 'CHL', halfDeg) =>
    request(`/ocean-layer?lat=${lat}&lon=${lon}&variable=${encodeURIComponent(variable)}`
            + (halfDeg ? `&half_deg=${halfDeg}` : '')),

  /** POST /api/v1/query - the conversational door. */
  query(payload) {
    return request('/query', { method: 'POST', body: payload });
  },

  /** GET /api/v1/health - also tells us demo mode and per-source status. */
  health() {
    return request('/health', { timeoutMs: 6000 });
  },

  /** GET /api/v1/evidence/{id} - the full chain behind an earlier answer. */
  evidence(queryId) {
    return request(`/evidence/${encodeURIComponent(queryId)}`);
  },

  /** GET /api/v1/sources - provider roles, access mechanisms, verification. */
  sources() {
    return request('/sources');
  },

  /** GET /api/v1/agents - agent contracts and the routing table. */
  agents() {
    return request('/agents');
  },

  /** GET /api/v1/pfz */
  pfz({ place, lat, lon } = {}) {
    return request(`/pfz${qs({ place, lat, lon })}`);
  },

  /** GET /api/v1/alerts */
  alerts({ place, lat, lon } = {}) {
    return request(`/alerts${qs({ place, lat, lon })}`);
  },

  /** GET /api/v1/marine-status */
  marineStatus({ place, lat, lon, activity, vessel } = {}) {
    return request(`/marine-status${qs({ place, lat, lon, activity, vessel })}`);
  },

  /** POST /api/v1/route-risk */
  routeRisk(payload) {
    return request('/route-risk', { method: 'POST', body: payload, timeoutMs: 20000 });
  },

  /** GET /api/v1/geo/basemap - coastline, zones and places as GeoJSON. */
  basemap() {
    return request('/geo/basemap');
  },

  /** GET /api/v1/geo/places - for manual location entry. */
  places(q) {
    return request(`/geo/places${qs({ q, limit: 200 })}`);
  },

  /** GET /api/v1/map-layers - layer provenance and authority flags. */
  mapLayers() {
    return request('/map-layers');
  },

  /** GET /api/v1/demo/scenarios */
  demoScenarios() {
    return request('/demo/scenarios');
  },
};

function qs(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

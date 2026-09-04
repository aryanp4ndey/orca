/**
 * Connectivity state: ONLINE, DEGRADED, OFFLINE.
 *
 * `navigator.onLine` only tells you whether a network interface exists, which
 * on a coastal 2G link is close to useless - the phone says "online" while
 * nothing completes. So we combine it with observed request latency and with
 * whether the last health probe actually answered.
 */

import { api } from '../api.js';

const listeners = new Set();
let status = 'online';
let lastLatency = null;
let lastOkAt = null;
let probeTimer = null;

export const NET = {
  get status() { return status; },
  get latency() { return lastLatency; },
  get lastOkAt() { return lastOkAt; },
};

export function onNetChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function set(next, latency) {
  if (latency !== undefined) lastLatency = latency;
  if (next === status) return;
  status = next;
  listeners.forEach((fn) => fn(status, lastLatency));
}

/** Called by the app after every request so state reflects reality, not guesses. */
export function observe({ ok, ms, kind }) {
  if (ok) {
    lastOkAt = Date.now();
    // Above ~2.5 s round trip the user is on a link where we should be showing
    // cached data and trimming payloads, whatever the browser claims.
    set(ms > 2500 ? 'degraded' : 'online', ms);
    return;
  }
  if (kind === 'offline' || !navigator.onLine) set('offline');
  else if (kind === 'timeout') set('degraded');
}

export function startProbing() {
  const check = async () => {
    if (!navigator.onLine) { set('offline'); return; }
    const started = performance.now();
    try {
      await api.health();
      observe({ ok: true, ms: Math.round(performance.now() - started) });
    } catch (err) {
      observe({ ok: false, kind: err.kind });
    }
  };
  window.addEventListener('online', check);
  window.addEventListener('offline', () => set('offline'));
  clearInterval(probeTimer);
  // Deliberately infrequent. Polling a backend every few seconds is exactly the
  // behaviour that ruins a metered coastal connection.
  probeTimer = setInterval(check, 60000);
  check();
}

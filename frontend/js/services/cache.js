/**
 * Answer cache for weak and absent connectivity.
 *
 * The rule this file exists to enforce: a saved answer may be shown, but it is
 * always shown *as* a saved answer, with the time it was retrieved. Stale data
 * is never presented as current - that is the difference between useful offline
 * behaviour and a dangerous one.
 */

const KEY = 'orca.answers.v1';
const LIMIT = 24;

function read() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; }
}

function write(items) {
  try { localStorage.setItem(KEY, JSON.stringify(items.slice(-LIMIT))); } catch { /* quota */ }
}

const signature = (query, ctx) =>
  [query.trim().toLowerCase(), ctx.mode, ctx.lang,
   ctx.location ? `${ctx.location.lat.toFixed(2)},${ctx.location.lon.toFixed(2)}` : 'none',
  ].join('|');

export function remember(query, ctx, response) {
  const items = read().filter((item) => item.signature !== signature(query, ctx));
  items.push({
    signature: signature(query, ctx),
    query,
    savedAt: Date.now(),
    response,
  });
  write(items);
}

export function recall(query, ctx) {
  const item = read().find((entry) => entry.signature === signature(query, ctx));
  if (!item) return null;
  return { ...item, ageMs: Date.now() - item.savedAt };
}

export function recent(limit = 6) {
  return read().slice(-limit).reverse()
    .map((item) => ({ ...item, ageMs: Date.now() - item.savedAt }));
}

export function clearAnswers() {
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}

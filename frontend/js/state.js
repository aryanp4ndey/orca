/**
 * Application state.
 *
 * One store, explicit subscriptions, no reactivity magic. Anything that should
 * survive a reload (mode, language, session, last answer) is persisted, because
 * a fisherman who loses signal mid-trip should reopen the app and still see what
 * ORCA last told them - clearly marked as saved, never as current.
 */

const KEY = 'orca.state.v1';

const DEFAULTS = {
  mode: 'fisher',                 // fisher | researcher | disaster | maritime
  lang: 'en',
  lowBandwidth: false,
  sessionId: null,
  location: null,                 // { lat, lon, accuracy, label, source }
  turns: [],                      // conversation history (answers included)
  lastAnswerAt: null,
  health: null,
  onboarded: false,
};

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    return { ...DEFAULTS, ...parsed, turns: Array.isArray(parsed.turns) ? parsed.turns : [] };
  } catch {
    return { ...DEFAULTS };
  }
}

export const state = load();

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Merge a patch and notify. `persist: false` for transient UI-only changes. */
export function update(patch, { persist = true, silent = false } = {}) {
  Object.assign(state, patch);
  if (persist) save();
  if (!silent) listeners.forEach((fn) => fn(state));
}

function save() {
  try {
    // Keep the stored history small: an old answer is useful, twenty are not,
    // and localStorage on a cheap phone is not free.
    const trimmed = {
      mode: state.mode, lang: state.lang, lowBandwidth: state.lowBandwidth,
      sessionId: state.sessionId, location: state.location,
      lastAnswerAt: state.lastAnswerAt, onboarded: state.onboarded,
      turns: state.turns.slice(-6).map((turn) => ({
        ...turn,
        response: turn.response ? stripHeavy(turn.response) : null,
      })),
    };
    localStorage.setItem(KEY, JSON.stringify(trimmed));
  } catch { /* private mode or quota - the app still works, just not across reloads */ }
}

/** Drop the parts of a response that are large and re-fetchable. */
function stripHeavy(response) {
  const { trace, visualizations, ...rest } = response;
  return {
    ...rest,
    visualizations: visualizations
      ? { markers: visualizations.markers, cards: visualizations.cards,
          charts: visualizations.charts, layers: [], timeline: [] }
      : undefined,
    __trimmed: true,
  };
}

export function addTurn(turn) {
  state.turns = [...state.turns, turn].slice(-40);
  update({ turns: state.turns, lastAnswerAt: Date.now() });
}

export function resetConversation() {
  update({ turns: [], sessionId: null });
}

import { ICON } from './util/dom.js';

export const MODES = {
  fisher: {
    id: 'fisher', get icon() { return ICON.boat; },
    activity: 'fishing_small_boat', vessel: 'small_motorised',
    detail: 'simple', showFactors: 4, defaultView: 'ask',
    quick: ['fishing', 'sea', 'warnings', 'pfz'],
  },
  researcher: {
    id: 'researcher', get icon() { return ICON.search; },
    activity: 'research', vessel: 'mechanised',
    detail: 'full', showFactors: 8, defaultView: 'ask',
    quick: ['sea', 'analytical', 'compare', 'evidence'],
  },
  disaster: {
    id: 'disaster', get icon() { return ICON.disaster; },
    activity: 'patrol', vessel: 'mechanised',
    detail: 'operational', showFactors: 6, defaultView: 'alerts',
    quick: ['warnings', 'avoid', 'sea', 'map'],
  },
  maritime: {
    id: 'maritime', get icon() { return ICON.ship || ICON.boat; },
    activity: 'cargo_transit', vessel: 'large',
    detail: 'operational', showFactors: 6, defaultView: 'ask',
    quick: ['route', 'sea', 'warnings', 'avoid'],
  },
};

export const mode = () => MODES[state.mode] || MODES.fisher;

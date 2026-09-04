/**
 * The answer card.
 *
 * Progressive disclosure is the whole design here. A fisherman sees a verdict,
 * three or four numbers and one sentence. A judge taps twice and sees the
 * evidence chain and the agent trace. Nobody is forced through the other
 * person's view.
 *
 * Two rules this file enforces:
 *   - risk is never communicated by colour alone: icon, word and colour always
 *     travel together, and the icon set is legible without reading;
 *   - a saved or stale answer is never drawn as though it were current.
 */

import { h, ICON, RISK_ICON } from '../util/dom.js';
import { dateTimeIST, icon as varIcon, num, timeIST, whenPhrase } from '../util/format.js';
import { t } from '../i18n.js';
import { mode, state } from '../state.js';
import { evidenceList, sourcePanel } from './evidence.js';
import { traceView } from './trace.js';

const VERDICT = {
  LOW: { en: 'Conditions look manageable', hi: 'स्थिति सामान्य है' },
  MODERATE: { en: 'Go only if you are prepared', hi: 'तैयारी के साथ ही जाएँ' },
  HIGH: { en: 'Not advisable today', hi: 'जाना ठीक नहीं है' },
  CRITICAL: { en: 'Do not go out', hi: 'बिलकुल न जाएँ' },
  INSUFFICIENT_DATA: { en: 'ORCA cannot confirm this', hi: 'ORCA पुष्टि नहीं कर सका' },
};

/** Never show a raw enum to a user. "INSUFFICIENT_DATA" is a code; "NOT KNOWN"
 *  is what it means, and the difference matters most in exactly the case where
 *  ORCA is refusing to give a verdict. */
export const LEVEL_WORD = {
  LOW: 'LOW', MODERATE: 'MODERATE', HIGH: 'HIGH', CRITICAL: 'CRITICAL',
  INSUFFICIENT_DATA: 'NOT KNOWN',
};

/** A disclosure section. Uses <details> so keyboard and screen readers get it free. */
export function disclose(title, iconGlyph, body, { open = false } = {}) {
  return h('details', { class: 'disclose', open },
    h('summary', { class: 'disclose__btn' },
      h('span', { 'aria-hidden': 'true' }, iconGlyph),
      h('span', {}, title),
      h('span', { class: 'disclose__chev', 'aria-hidden': 'true' }, ICON.chevron)),
    h('div', { class: 'disclose__body' }, body));
}

export function tag(text, kind = 'neutral') {
  return h('span', { class: `tag tag--${kind}` }, text);
}

/** Freshness as words plus a dot colour - never colour on its own. */
export function freshnessTag(freshness) {
  const label = {
    FRESH: 'Fresh', AGING: 'Ageing', STALE: 'Stale', UNAVAILABLE: 'Not available',
  }[freshness] || freshness;
  return tag(label, freshness);
}

function contextRow(response) {
  const bits = [];
  if (response.location?.name) {
    bits.push(h('span', {}, h('span', { 'aria-hidden': 'true' }, ICON.location),
      response.location.name));
  }
  if (response.time?.target) {
    bits.push(h('span', {}, h('span', { 'aria-hidden': 'true' }, ICON.time),
      whenPhrase(response.time.target, state.lang)));
  }
  if (response.activity) {
    bits.push(h('span', {}, h('span', { 'aria-hidden': 'true' }, ICON.boat),
      response.activity.replace(/_/g, ' ')));
  }
  return bits.length ? h('div', { class: 'risk__context' }, ...bits) : null;
}

/** The headline factors. Fisher mode gets three; a researcher gets all of them. */
function factorGrid(response) {
  const limit = mode().showFactors;
  const factors = (response.factors?.length ? response.factors
    : (response.risk?.factors || []).map((f) => ({
        label: f.label, variable: f.variable, value: f.value,
        unit: f.unit, level: f.level, rationale: f.rationale,
      })))
    .slice(0, limit);
  if (!factors.length) return null;

  return h('div', { class: 'factors' }, ...factors.map((f) =>
    h('div', { class: 'factor', 'data-level': f.level || 'LOW' },
      h('div', { class: 'factor__top' },
        h('span', { 'aria-hidden': 'true' }, varIcon(f.variable)),
        h('span', {}, f.label)),
      h('div', {},
        h('span', { class: 'factor__value' }, num(f.value)),
        f.unit ? h('span', { class: 'factor__unit' }, f.unit) : null),
      h('div', { class: 'factor__level' }, f.level || ''))));
}

function warningStrips(response) {
  const strips = [];
  const risk = response.risk;

  if (risk?.decision_status === 'ADVISORY_WITHHELD') {
    strips.push(h('div', { class: 'warnstrip', role: 'alert' },
      h('span', { class: 'warnstrip__icon', 'aria-hidden': 'true' }, ICON.warn),
      h('div', {},
        h('strong', {}, t('cannotVerify')), ' ',
        risk.gate_reason ? h('span', {}, risk.gate_reason) : null)));
  } else if (risk?.decision_status === 'ADVISORY_DEGRADED') {
    strips.push(h('div', { class: 'warnstrip warnstrip--info' },
      h('span', { class: 'warnstrip__icon', 'aria-hidden': 'true' }, ICON.warn),
      h('div', {}, risk.gate_reason
        || 'Some readings are older than they should be. Check the official advisory.')));
  }

  // Authority warnings, quoted rather than paraphrased.
  for (const warning of (risk?.warnings || []).slice(0, 3)) {
    strips.push(h('div', { class: 'warnstrip warnstrip--info' },
      h('span', { class: 'warnstrip__icon', 'aria-hidden': 'true' }, ICON.alert),
      h('div', {}, warning)));
  }

  if (response.demo_mode) {
    strips.push(h('div', { class: 'warnstrip warnstrip--muted' },
      h('span', { class: 'warnstrip__icon', 'aria-hidden': 'true' }, ICON.info),
      h('div', {}, h('strong', {}, t('demoData')), ' — ', t('demoNote'))));
  }
  return strips;
}

/** Strip the caveat lines out of the backend answer - they are rendered as
 *  their own strips and as the card footer, and repeating them in the body
 *  makes the card unreadable. */
export function narrative(response) {
  return String(response.answer || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith('!'))
    .filter((line) => !line.startsWith('ORCA is a decision-support prototype'))
    .filter((line) => !line.startsWith('Based on '));
}

export function answerCard(response, { onMap, onCompare, cached = null } = {}) {
  const risk = response.risk;
  const level = risk?.risk_level || 'INSUFFICIENT_DATA';
  const lang = state.lang;
  const lines = narrative(response);
  const detail = mode().detail;

  const card = h('article', {
    class: 'risk', 'data-level': level,
    'aria-label': `Marine risk: ${LEVEL_WORD[level] || level}`,
  });

  card.appendChild(h('div', { class: 'risk__band', 'aria-hidden': 'true' }));

  card.appendChild(h('div', { class: 'risk__head' },
    h('div', { class: 'risk__icon', 'aria-hidden': 'true' }, RISK_ICON[level] || '❓'),
    h('div', { class: 'grow' },
      h('div', { class: 'risk__label' }, 'MARINE RISK'),
      h('div', { class: 'risk__level' }, LEVEL_WORD[level] || level),
      h('div', { class: 'risk__verdict' },
        (VERDICT[level] || {})[lang] || (VERDICT[level] || {}).en || ''),
      contextRow(response))));

  if (cached) {
    card.appendChild(h('div', { class: 'warnstrip warnstrip--muted' },
      h('span', { class: 'warnstrip__icon', 'aria-hidden': 'true' }, ICON.offline),
      h('div', {}, h('strong', {}, t('cachedAnswer')), ' — ',
        `${t('lastUpdated')} ${dateTimeIST(new Date(cached.savedAt).toISOString())}`)));
  }

  const grid = factorGrid(response);
  if (grid) card.appendChild(grid);

  for (const strip of warningStrips(response)) card.appendChild(strip);

  // Level 1 disclosure: why.
  card.appendChild(disclose(t('why'), ICON.info,
    h('div', {},
      ...lines.slice(1).map((line) => h('p', {}, line)),
      risk ? h('p', { class: 'tiny muted' },
        `Score ${num(risk.risk_score)}/100 · confidence ${Math.round((risk.confidence || 0) * 100)}%`
        + ` · ruleset ${risk.ruleset_id}@${risk.ruleset_version}`) : null),
    { open: detail !== 'simple' }));

  // Level 2 disclosure: the evidence chain.
  if (response.evidence?.length) {
    card.appendChild(disclose(
      `${t('viewEvidence')} (${response.evidence.length})`, ICON.book,
      evidenceList(response.evidence, { limit: detail === 'simple' ? 6 : 40 })));
  }

  if (response.sources?.length) {
    card.appendChild(disclose(t('sources'), ICON.satellite, sourcePanel(response)));
  }

  // Level 3 disclosure: how the answer was produced.
  if (response.trace) {
    card.appendChild(disclose(t('howDecided'), ICON.chart, traceView(response)));
  }

  const actions = h('div', { class: 'risk__actions' });
  if (onMap) {
    actions.appendChild(h('button', { class: 'btn btn--sm', type: 'button', onclick: onMap },
      h('span', { 'aria-hidden': 'true' }, ICON.map), ' ', t('viewMap')));
  }
  if (onCompare && response.time?.target) {
    actions.appendChild(h('button', { class: 'btn btn--sm', type: 'button', onclick: onCompare },
      h('span', { 'aria-hidden': 'true' }, ICON.chart), ' ', t('compare')));
  }
  if (actions.childNodes.length) card.appendChild(actions);

  card.appendChild(h('div', { class: 'card__note' },
    response.disclaimer || t('disclaimer')));

  return card;
}

/** Compact answer for non-risk intents (sea state, weather, PFZ, alerts, …). */
export function plainAnswer(response) {
  const lines = narrative(response);
  return h('article', { class: 'card' },
    h('div', { class: 'card__head' },
      h('div', { class: 'card__title' }, lines[0] || 'ORCA'),
      response.demo_mode ? tag(t('demoData'), 'DEMO') : null),
    h('div', { class: 'stack stack--tight', style: { padding: '0 16px 16px' } },
      ...lines.slice(1).map((line) => h('p', { class: 'dim' }, line))),
    response.evidence?.length
      ? disclose(`${t('viewEvidence')} (${response.evidence.length})`, ICON.book,
                 evidenceList(response.evidence, { limit: 12 }))
      : null,
    response.trace ? disclose(t('howDecided'), ICON.chart, traceView(response)) : null);
}

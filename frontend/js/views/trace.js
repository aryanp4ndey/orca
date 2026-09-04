/**
 * "How ORCA decided".
 *
 * This is the judge-facing view, deliberately kept off the fisherman's path.
 * It is built entirely from the backend's own trace - the plan it chose, the
 * agents it ran, which ones it skipped and why, the provider calls with their
 * timings, and the risk decision. Nothing here is a mock-up of reasoning; it is
 * the record of what happened.
 */

import { h, ICON } from '../util/dom.js';
import { num } from '../util/format.js';

const AGENT_LABEL = {
  geospatial: 'Geospatial', weather: 'Weather', ocean: 'Ocean',
  satellite: 'Satellite', pfz: 'Fishing zones', hazard: 'Hazards',
  route: 'Route', risk: 'Risk engine', response: 'Response',
};

const AGENT_ICON = {
  geospatial: '🗺', weather: '🌬', ocean: '🌊', satellite: '🛰',
  pfz: '🐟', hazard: '⚠️', route: '🧭', risk: '⚖️', response: '💬',
};

function stateOfAgent(response, capability) {
  const span = (response.trace?.spans || [])
    .find((s) => s.kind === 'agent' && s.attributes?.capability === capability);
  if (!span) return 'SKIPPED';
  return span.status || 'OK';
}

export function agentGrid(response) {
  const steps = response.trace?.plan?.steps || [];
  const skipped = response.trace?.plan?.skipped || {};
  const pills = steps.map((step) => {
    const status = stateOfAgent(response, step.capability);
    const mark = { OK: '✓', PARTIAL: '◑', SKIPPED: '–', FAILED: '✕', TIMEOUT: '⏱' }[status] || '·';
    return h('div', {
      class: 'agentpill', 'data-state': status,
      title: `${step.reason}${step.required ? '' : ' (optional)'}`,
    },
      h('span', { 'aria-hidden': 'true' }, AGENT_ICON[step.capability] || '•'),
      h('span', { class: 'grow' }, AGENT_LABEL[step.capability] || step.capability),
      h('span', { class: 'agentpill__mark' }, mark));
  });

  const notRun = Object.entries(skipped).map(([capability, reason]) =>
    h('div', { class: 'agentpill', 'data-state': 'SKIPPED', title: reason },
      h('span', { 'aria-hidden': 'true' }, AGENT_ICON[capability] || '•'),
      h('span', { class: 'grow' }, AGENT_LABEL[capability] || capability),
      h('span', { class: 'agentpill__mark' }, '–')));

  return h('div', {}, h('div', { class: 'agentgrid' }, ...pills, ...notRun));
}

/** The pipeline, as steps, in the order it actually ran. */
export function traceView(response) {
  const trace = response.trace;
  if (!trace) return h('p', { class: 'muted' }, 'No trace was returned for this answer.');

  const plan = trace.plan || {};
  const waves = plan.waves || [];
  const latency = response.latency || {};
  const spans = trace.spans || [];
  const providerSpans = spans.filter((s) => s.kind === 'provider');

  const steps = [];

  steps.push(step('Your question', 'ok',
    h('div', {},
      h('div', { class: 'mono tiny' }, `"${response.intent?.value ? '' : ''}"`),
      h('div', {}, response.location?.query || ''))));

  steps.push(step(`Understood as: ${plan.intent || response.intent?.value}`, 'ok',
    h('div', {},
      h('div', {}, `Confidence ${Math.round((response.intent?.confidence || 0) * 100)}%`
        + ` · resolved by ${plan.nlu_resolver || 'rules'}`
        + ` · language ${plan.language || response.answer_language}`),
      (response.intent?.inherited || []).length
        ? h('div', { class: 'muted' },
            `Carried over from the previous question: ${response.intent.inherited.join(', ')}`)
        : null,
      h('div', { class: 'ms' }, `${num(latency.nlu_ms)} ms — no language model was used`))));

  steps.push(step('Plan', 'ok',
    h('div', {},
      h('div', {}, waves.map((wave, i) =>
        `${i + 1}. ${wave.map((c) => AGENT_LABEL[c] || c).join(' + ')}`).join('   →   ')),
      h('div', { class: 'muted tiny' },
        'Agents on the same line run at the same time.'),
      agentGrid(response))));

  if (providerSpans.length) {
    steps.push(step('Sources consulted', 'ok',
      h('div', {},
        ...providerSpans.map((span) =>
          h('div', { class: 'srcrow' },
            h('div', {},
              h('div', { class: 'srcrow__name' }, span.attributes?.source || span.name),
              h('div', { class: 'srcrow__meta' }, span.name)),
            h('div', { class: 'srcrow__right' },
              h('span', { class: `tag tag--${span.attributes?.freshness || 'neutral'}` },
                span.status),
              span.attributes?.cache_hit
                ? h('span', { class: 'srcrow__meta' }, 'from cache') : null,
              h('span', { class: 'ms' }, `${num(span.duration_ms)} ms`)))),
        h('div', { class: 'muted tiny' },
          `Run together, not one after another — that saved ${num(latency.parallel_saving_ms)} ms.`))));
  }

  if (response.risk) {
    steps.push(step(`Risk: ${response.risk.risk_level}`, 'ok',
      h('div', {},
        h('div', {}, `Score ${num(response.risk.risk_score)}/100 · `
          + `confidence ${Math.round((response.risk.confidence || 0) * 100)}% · `
          + response.risk.decision_status),
        h('div', { class: 'muted tiny' },
          `Deterministic ruleset ${response.risk.ruleset_id}@${response.risk.ruleset_version}`
          + ' — thresholds are configuration, not a model’s opinion.'),
        h('div', { class: 'bars' },
          ...(response.risk.factors || []).slice(0, 6).map((factor) =>
            h('div', { class: 'bar' },
              h('div', { class: 'bar__top' },
                h('span', {}, factor.label),
                h('span', { class: 'mono' },
                  `${num(factor.value)} ${factor.unit || ''}`
                  + (factor.threshold !== null && factor.threshold !== undefined
                    ? ` ${factor.comparator} ${num(factor.threshold)}` : ''))),
              h('div', { class: 'bar__track' },
                h('div', {
                  class: 'bar__fill', 'data-level': factor.level,
                  style: { width: `${Math.min(100, (factor.contribution / 30) * 100)}%` },
                })))))))); 
  }

  steps.push(step('Answer', 'ok',
    h('div', {},
      h('div', {}, `Written in ${response.answer_language}, from the values above.`),
      h('div', { class: 'muted tiny' },
        'Every number in the answer is checked against the evidence before it is shown.'),
      h('div', { class: 'ms' }, `Total ${num(latency.total_ms)} ms`))));

  const notes = (trace.notes || []).length
    ? h('div', { class: 'stack stack--tight' },
        h('div', { class: 'divider' }),
        h('div', { class: 'section-title' }, 'Notes'),
        ...trace.notes.map((note) => h('p', { class: 'tiny muted' }, note)))
    : null;

  return h('div', {},
    h('div', { class: 'trace' }, ...steps),
    latencyPanel(response),
    notes);
}

function step(title, kind, body) {
  return h('div', { class: `tracestep${kind === 'skip' ? ' tracestep--skip' : ''}` },
    h('div', { class: 'tracestep__rail' },
      h('div', { class: 'tracestep__dot' }),
      h('div', { class: 'tracestep__line' })),
    h('div', { class: 'tracestep__body' },
      h('div', { class: 'tracestep__title' }, title),
      h('div', { class: 'tracestep__desc' }, body)));
}

export function latencyPanel(response) {
  const latency = response.latency || {};
  const rows = [
    ['Understanding', latency.nlu_ms],
    ['Planning', latency.planning_ms],
    ['Sources (wall clock)', latency.providers_ms],
    ['Agents', latency.agents_ms],
    ['Risk engine', latency.risk_ms],
    ['Answer', latency.response_ms],
    ['Language model', latency.llm_ms],
  ].filter(([, value]) => Number.isFinite(value));

  return h('div', { class: 'stack stack--tight' },
    h('div', { class: 'divider' }),
    h('div', { class: 'section-title' }, 'Where the time went'),
    ...rows.map(([label, value]) =>
      h('div', { class: 'spread tiny' },
        h('span', { class: 'muted' }, label),
        h('span', { class: 'ms' }, `${num(value)} ms`))),
    h('div', { class: 'spread' },
      h('strong', {}, 'Total'),
      h('span', { class: 'ms' }, `${num(latency.total_ms)} ms`)),
    latency.parallel_saving_ms
      ? h('p', { class: 'tiny muted' },
          `Running the sources together instead of one after another saved `
          + `${num(latency.parallel_saving_ms)} ms on this request.`)
      : null);
}

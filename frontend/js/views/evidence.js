/**
 * Evidence and source panels.
 *
 * This is the screen that answers "how do you know?". Every row shows the
 * source, the dataset, the variable, the value with its unit, the time it
 * describes, the time it was issued, the time ORCA fetched it, and a freshness
 * verdict. Nothing is summarised away, because the point of the panel is that
 * it can be checked.
 */

import { h, ICON } from '../util/dom.js';
import { dateTimeIST, icon as varIcon, num, relativeAge, timeIST } from '../util/format.js';
import { t } from '../i18n.js';

const ORIGIN_LABEL = {
  LIVE: 'Live', DEMO: 'Demo', CACHED_LIVE: 'Cached live', COMPUTED: 'Computed by ORCA',
  MIXED: 'Mixed',
};

export function evidenceRow(item) {
  const times = [];
  if (item.forecast_time) {
    times.push(h('span', {}, `${t('forecast')} ${timeIST(item.forecast_time)}`));
  }
  if (item.observation_time && !item.forecast_time) {
    times.push(h('span', {}, `Observed ${timeIST(item.observation_time)}`));
  }
  if (item.issued_at) {
    times.push(h('span', {}, `${t('issued')} ${dateTimeIST(item.issued_at)}`));
  }
  times.push(h('span', {}, `${t('retrieved')} ${timeIST(item.retrieved_at)}`));
  if (Number.isFinite(item.age_seconds)) {
    times.push(h('span', { class: 'muted' }, relativeAge(item.age_seconds)));
  }

  return h('div', { class: 'ev' },
    h('div', { class: 'ev__top' },
      h('span', { class: 'ev__src' }, item.source),
      h('span', { 'aria-hidden': 'true' }, varIcon(item.variable)),
      h('span', { class: 'ev__var' }, item.variable.replace(/_/g, ' ')),
      h('span', { class: 'grow' }),
      h('span', { class: `tag tag--${item.freshness}` },
        { FRESH: 'Fresh', AGING: 'Ageing', STALE: 'Stale',
          UNAVAILABLE: 'No value' }[item.freshness] || item.freshness),
      h('span', { class: `tag tag--${item.origin}` },
        ORIGIN_LABEL[item.origin] || item.origin)),
    h('div', { class: 'ev__val' },
      item.value === null || item.value === undefined
        ? h('span', { class: 'muted' }, 'not retrieved')
        : `${num(item.value)}${item.unit ? ` ${item.unit}` : ''}`),
    h('div', { class: 'ev__times' }, ...times),
    h('div', { class: 'ev__times mono tiny' },
      h('span', {}, item.dataset),
      item.agent ? h('span', {}, item.agent) : null,
      item.cache_hit ? h('span', {}, 'from cache') : null),
    item.transformation ? h('div', { class: 'ev__note' }, item.transformation) : null,
    item.notes ? h('div', { class: 'ev__note' }, item.notes) : null);
}

export function evidenceList(evidence, { limit = 40 } = {}) {
  if (!evidence?.length) {
    return h('p', { class: 'muted' }, 'No evidence was recorded for this answer.');
  }
  // Retrieved values first, computed ones after: the user cares most about what
  // came from an authority.
  const ordered = [...evidence].sort((a, b) => {
    const rank = (e) => (e.origin === 'COMPUTED' ? 1 : 0);
    return rank(a) - rank(b);
  });
  const shown = ordered.slice(0, limit);
  return h('div', { class: 'stack stack--tight' },
    ...shown.map(evidenceRow),
    ordered.length > shown.length
      ? h('p', { class: 'tiny muted' },
          `${ordered.length - shown.length} more rows — open “Technical details”.`)
      : null);
}

export function sourcePanel(response) {
  const rows = (response.sources || []).map((source) =>
    h('div', { class: 'srcrow' },
      h('div', {},
        h('div', { class: 'srcrow__name' }, source.source),
        h('div', { class: 'srcrow__meta' }, source.dataset || source.provider),
        source.attribution
          ? h('div', { class: 'srcrow__meta' }, source.attribution) : null,
        source.error ? h('div', { class: 'srcrow__meta' }, source.error) : null),
      h('div', { class: 'srcrow__right' },
        h('span', { class: `tag tag--${source.freshness}` }, source.freshness),
        h('span', { class: 'srcrow__meta' },
          `${source.status}${source.cache_hit ? ' · cached' : ''}`),
        Number.isFinite(source.latency_ms)
          ? h('span', { class: 'ms' }, `${Math.round(source.latency_ms)} ms`) : null)));

  const freshness = response.freshness || {};
  return h('div', { class: 'stack stack--tight' },
    ...rows,
    h('div', { class: 'divider' }),
    h('p', { class: 'tiny muted' },
      `Overall freshness: ${freshness.overall || '—'}`
      + (freshness.stale_sources?.length
        ? ` · stale: ${freshness.stale_sources.join(', ')}` : '')),
    (response.conflicts || []).length
      ? h('div', { class: 'stack stack--tight' },
          h('div', { class: 'section-title' }, 'Source disagreement'),
          ...response.conflicts.map((conflict) =>
            h('div', { class: 'ev' },
              h('div', { class: 'ev__top' },
                h('span', { class: 'ev__src' }, conflict.variable.replace(/_/g, ' ')),
                h('span', { class: 'grow' }),
                h('span', { class: 'tag tag--AGING' }, conflict.severity)),
              h('div', { class: 'ev__times' },
                ...conflict.claims.map((claim) =>
                  h('span', {}, `${claim.source}: ${num(claim.value)} ${claim.unit || ''}`))),
              h('div', { class: 'ev__note' }, conflict.resolution))))
      : null);
}

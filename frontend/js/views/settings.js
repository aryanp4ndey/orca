/**
 * Settings and the system panel.
 *
 * The system panel is deliberately included: for a judge, "what is real here?"
 * is the first question, and the honest answer is a list of every source with
 * its access mechanism and whether that access has been verified. It comes
 * straight from GET /api/v1/sources and GET /api/v1/health.
 */

import { h, ICON, toast } from '../util/dom.js';
import { dateTimeIST, num } from '../util/format.js';
import { LANGUAGES, setLang, t } from '../i18n.js';
import { MODES, state, update } from '../state.js';
import { api } from '../api.js';
import { CONFIG, setApiBase } from '../config.js';
import { clearAnswers } from '../services/cache.js';

export function modeChooser(onPick) {
  const container = h('div', { class: 'radioset', role: 'radiogroup', 'aria-label': t('mode') });
  const buttons = Object.values(MODES).map((m) => {
    const btn = h('button', {
      class: 'radio', type: 'button', role: 'radio', id: `mode-${m.id}`,
      'aria-checked': String(state.mode === m.id),
      'data-active': state.mode === m.id ? 'true' : null,
      onclick: () => {
        update({ mode: m.id });
        document.documentElement.dataset.mode = m.id;
        buttons.forEach(b => {
          const isSelected = state.mode === b.id.replace('mode-', '');
          b.setAttribute('aria-checked', String(isSelected));
          if (isSelected) b.setAttribute('data-active', 'true');
          else b.removeAttribute('data-active');
        });
        onPick?.(m.id);
      },
    },
      h('span', { class: 'radio__icon', 'aria-hidden': 'true' }, m.icon),
      h('span', { class: 'grow' },
        h('span', { class: 'radio__name' }, t(`modes.${m.id}.name`)),
        h('span', { class: 'radio__desc' }, t(`modes.${m.id}.desc`))));
    return btn;
  });
  buttons.forEach(b => container.appendChild(b));
  return container;
}

function toggle(id, label, hint, checked, onChange) {
  return h('label', { class: 'switch', for: id },
    h('span', { class: 'grow' },
      h('span', { class: 'radio__name' }, label),
      hint ? h('span', { class: 'radio__desc' }, hint) : null),
    h('input', {
      type: 'checkbox', id, checked, class: 'visually-hidden',
      onchange: (e) => onChange(e.target.checked),
    }),
    h('span', { class: 'switch__track', 'aria-hidden': 'true' },
      h('span', { class: 'switch__thumb' })));
}

export function settingsScreen(app) {
  const container = h('div', { class: 'stack' });

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.fisher), ' ', t('mode')));
  container.appendChild(modeChooser(() => app.refreshShell()));

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.book), ' ', t('language')));
  container.appendChild(h('div', { class: 'chips' }, ...LANGUAGES.map((language) =>
    h('button', {
      class: 'chip', type: 'button', id: `lang-${language.code}`,
      'data-active': state.lang === language.code ? 'true' : null,
      onclick: () => {
        update({ lang: language.code });
        setLang(language.code);
        app.refreshShell();
        app.go('more');
      },
    }, language.native))));
  container.appendChild(h('p', { class: 'tiny muted' },
    'ORCA understands more languages than it answers in, including Hindi typed in '
    + 'Roman letters. If it cannot answer in your language it falls back to English '
    + 'and says so.'));

  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.settings), ' ', t('settings')));
  container.appendChild(h('div', { class: 'card' },
    h('div', { style: { padding: '4px 16px' } },
      toggle('low-bw', t('lowBandwidth'), t('lowBandwidthNote'), state.lowBandwidth,
        (checked) => {
          update({ lowBandwidth: checked });
          document.documentElement.dataset.lowbw = checked ? 'true' : 'false';
          toast(checked ? 'Low-bandwidth mode on' : 'Low-bandwidth mode off');
        }),
      toggle('speak-answers', 'Read answers aloud',
        'Uses your device’s voice, where it has one.', Boolean(state.speakAnswers),
        (checked) => update({ speakAnswers: checked })))));

  const system = h('div', { class: 'stack' });
  container.appendChild(h('div', { class: 'section-title' },
    h('span', { 'aria-hidden': 'true' }, ICON.satellite), ' What is real here'));
  container.appendChild(system);

  (async () => {
    try {
      const [health, sources, agents] = await Promise.all([
        api.health(), api.sources(), api.agents(),
      ]);
      system.appendChild(h('div', { class: 'card' },
        h('div', { class: 'card__head' },
          h('div', { class: 'card__title' }, `${health.app} ${health.version}`),
          h('span', { class: `tag tag--${health.demo_mode ? 'DEMO' : 'LIVE'}` },
            health.demo_mode ? t('demoData') : 'LIVE')),
        h('div', { style: { padding: '0 16px 16px' } },
          h('p', { class: 'tiny muted' },
            `${health.environment} · uptime ${num(health.uptime_seconds)} s · `
            + `language model: ${health.llm?.available ? health.llm.model : 'not used'}`),
          ...(health.warnings || []).map((warning) =>
            h('p', { class: 'tiny muted' }, `! ${warning}`)))));

      system.appendChild(h('div', { class: 'card card--flush' },
        ...sources.providers.map((provider) =>
          h('div', { class: 'srcrow' },
            h('div', {},
              h('div', { class: 'srcrow__name' },
                `${provider.source}`,
                provider.not_configured
                  ? h('span', { class: 'tag tag--neutral' }, 'not configured') : null),
              h('div', { class: 'srcrow__meta' }, provider.role),
              h('div', { class: 'srcrow__meta' }, provider.access_mechanism),
              provider.verification_note
                ? h('div', { class: 'srcrow__meta' }, provider.verification_note) : null),
            h('div', { class: 'srcrow__right' },
              h('span', { class: `tag tag--${provider.origin}` }, provider.origin),
              h('span', { class: `tag tag--${provider.verified_access ? 'FRESH' : 'AGING'}` },
                provider.verified_access ? 'access verified' : 'access unverified'))))));

      system.appendChild(h('div', { class: 'card' },
        h('div', { class: 'card__head' },
          h('div', { class: 'card__title' }, `${agents.agents.length} agents`)),
        h('div', { class: 'agentgrid', style: { padding: '0 16px 16px' } },
          ...agents.agents.map((agent) =>
            h('div', { class: 'agentpill', 'data-state': agent.optional ? 'SKIPPED' : 'OK',
                       title: agent.responsibility },
              h('span', { class: 'grow' }, agent.name.replace(/_agent$/, '')),
              h('span', { class: 'agentpill__mark' }, agent.optional ? '○' : '●'))))));
    } catch (err) {
      system.appendChild(h('p', { class: 'tiny muted' },
        `Could not reach the backend: ${err.message}`));
    }
  })();

  container.appendChild(h('div', { class: 'section-title' }, 'Connection'));
  const apiInput = h('input', { class: 'input', id: 'api-base',
                                value: CONFIG.apiBase || '(same origin)' });
  container.appendChild(h('div', { class: 'card' },
    h('div', { style: { padding: '16px' } },
      h('div', { class: 'field' },
        h('label', { class: 'label', for: 'api-base' }, 'Backend address'),
        apiInput),
      h('div', { class: 'row' },
        h('button', { class: 'btn btn--sm', type: 'button', onclick: () => {
          const value = apiInput.value.trim();
          setApiBase(value === '(same origin)' ? '' : value);
          toast('Backend address saved. Reloading…');
          setTimeout(() => location.reload(), 600);
        } }, 'Save'),
        h('button', { class: 'btn btn--sm btn--ghost', type: 'button', onclick: () => {
          clearAnswers();
          toast('Saved answers cleared.');
        } }, 'Clear saved answers')))));

  container.appendChild(h('p', { class: 'tiny muted' },
    'ORCA — Marine EcOsystem Reasoning with Collaborative Agents. '
    + 'SIH26176 · ISRO · Team DRISHTI (138). '
    + 'Decision support, not a certified navigation or maritime-safety system.'));
  return container;
}

/**
 * Progress while a query is in flight.
 *
 * The stages listed are the real pipeline stages, in the real order. What we do
 * NOT do is tick them off as complete - the client cannot observe the backend's
 * internal progress, and pretending otherwise would be inventing telemetry. So
 * the panel shows which stage is *expected* to be running and nothing more; the
 * moment the answer lands it is replaced by the actual measured timings from the
 * response trace.
 */

import { h } from '../util/dom.js';
import { t } from '../i18n.js';

const STAGES = [
  { at: 0,    en: 'Understanding your request…',       hi: 'आपका सवाल समझ रहे हैं…' },
  { at: 350,  en: 'Choosing which sources to ask…',    hi: 'स्रोत चुन रहे हैं…' },
  { at: 900,  en: 'Checking weather and sea state…',   hi: 'मौसम और समुद्र देख रहे हैं…' },
  { at: 2200, en: 'Assessing risk…',                   hi: 'जोखिम आँक रहे हैं…' },
  { at: 5000, en: 'Still working — the connection may be slow…',
              hi: 'अभी भी काम जारी है — कनेक्शन धीमा हो सकता है…' },
];

export function progressPanel(lang = 'en') {
  const label = h('span', {}, STAGES[0][lang] || STAGES[0].en);
  const panel = h('div', { class: 'progress', role: 'status', 'aria-live': 'polite' },
    h('span', { class: 'pstep__mark', 'aria-hidden': 'true' }),
    label);

  const started = performance.now();
  const timer = setInterval(() => {
    const elapsed = performance.now() - started;
    const stage = [...STAGES].reverse().find((s) => elapsed >= s.at) || STAGES[0];
    label.textContent = stage[lang] || stage.en;
  }, 250);

  panel.stop = () => clearInterval(timer);
  return panel;
}

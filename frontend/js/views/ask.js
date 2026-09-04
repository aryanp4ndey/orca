/**
 * The ask screen: home and conversation in one surface.
 *
 * Empty, it is a home page - a single question box, a microphone, a location
 * button and four things worth tapping. With a conversation in it, it is a
 * thread. A fisherman never navigates anywhere to get an answer.
 */

import { h, ICON, RISK_ICON, renderIcons, announce, toast } from '../util/dom.js';
import { dateTimeIST, whenPhrase } from '../util/format.js';
import { t, getLang } from '../i18n.js';
import { state, mode, addTurn, update, resetConversation } from '../state.js';
import { api, ApiError } from '../api.js';
import { NET, observe } from '../services/net.js';
import * as voice from '../services/voice.js';
import { recall, remember, recent } from '../services/cache.js';
import { answerCard, plainAnswer } from './answer.js';
import { progressPanel } from './progress.js';

const QUICK = {
  fishing: { icon: 'fisher', key: 'quickFishing',
             query: { en: 'Is it safe to go fishing from {place} tomorrow at 7 AM?',
                      hi: 'क्या कल सुबह 7 बजे {place} से मछली पकड़ने जाना सुरक्षित है?' } },
  sea:     { icon: 'wave', key: 'quickSea',
             query: { en: 'What is the sea condition near {place}?',
                      hi: '{place} के पास समुद्र की स्थिति क्या है?' } },
  warnings:{ icon: 'warn', key: 'quickWarnings',
             query: { en: 'Are there any cyclone or lightning warnings near {place}?',
                      hi: 'क्या {place} के पास चक्रवात या बिजली की चेतावनी है?' } },
  pfz:     { icon: 'fish', key: 'quickPFZ',
             query: { en: 'Where is the nearest Potential Fishing Zone today?',
                      hi: 'आज निकटतम मछली क्षेत्र कहाँ है?' } },
  avoid:   { icon: 'danger', key: 'quickWarnings',
             query: { en: 'What areas should I avoid near {place}?',
                      hi: '{place} के पास किन क्षेत्रों से बचें?' } },
  analytical: { icon: 'chart', key: 'quickSea',
             query: { en: 'Why is fishing potential lower here between 5 PM and 10 PM?',
                      hi: 'यहाँ शाम 5 से 10 बजे मछली की संभावना कम क्यों है?' } },
  route:   { icon: 'route', key: 'route',
             query: { en: 'Show the safest route from Kochi to Mangaluru',
                      hi: 'कोच्चि से मंगलुरु तक सबसे सुरक्षित मार्ग दिखाएँ' } },
  compare: { icon: 'chart', key: 'compare', view: 'compare' },
  evidence:{ icon: 'book', key: 'viewEvidence', view: 'evidence' },
  map:     { icon: 'map', key: 'map', view: 'map' },
};

export function askView(app) {
  const container = h('div', { class: 'stack' });
  const thread = h('div', { class: 'thread', id: 'thread' });

  const input = h('input', {
    class: 'askbox__input', id: 'ask-input', type: 'text',
    placeholder: t('askPlaceholder'), 'aria-label': t('askTitle'),
    autocomplete: 'off', autocapitalize: 'sentences',
    onkeydown: (e) => { if (e.key === 'Enter') submit(); },
  });

  const micButton = voice.isAvailable()
    ? h('button', { class: 'iconbtn mic', type: 'button', id: 'mic-btn',
                    'aria-label': t('speak'), onclick: () => startVoice() },
        h('span', { 'aria-hidden': 'true' }, ICON.mic))
    : null;

  const sendButton = h('button', {
    class: 'btn btn--primary', type: 'button', id: 'ask-send',
    'aria-label': t('send'), onclick: () => submit(),
  }, h('span', { 'aria-hidden': 'true' }, ICON.send));

  const askbox = h('div', { class: 'askbox' },
    h('div', { class: 'askbox__row' }, input, micButton, sendButton));

  // ---- rendering ---------------------------------------------------------
  function renderThread() {
    while (thread.firstChild) thread.removeChild(thread.firstChild);
    for (const turn of state.turns) {
      thread.appendChild(h('div', { class: 'msg msg--user' },
        h('div', { class: 'bubble' }, turn.query)));
      if (turn.response) {
        thread.appendChild(h('div', { class: 'msg' }, renderAnswer(turn)));
      } else if (turn.error) {
        thread.appendChild(h('div', { class: 'msg' }, errorCard(turn)));
      }
    }
    thread.scrollTop = thread.scrollHeight;
    requestAnimationFrame(renderIcons);
  }

  function renderAnswer(turn) {
    const response = turn.response;
    const wrapper = h('div', {});
    const isRisk = Boolean(response.risk)
      && ['marine_safety', 'sea_condition', 'route_risk'].includes(response.intent?.value);
    wrapper.appendChild(isRisk
      ? answerCard(response, {
          onMap: () => app.go('map', { response }),
          onCompare: () => app.go('compare', { response }),
          cached: turn.cached || null,
        })
      : plainAnswer(response));

    if (response.follow_up_suggestions?.length && turn === state.turns[state.turns.length - 1]) {
      wrapper.appendChild(h('div', { class: 'chips', style: { marginTop: '12px' } },
        ...response.follow_up_suggestions.slice(0, 3).map((suggestion) =>
          h('button', { class: 'chip', type: 'button',
                        onclick: () => ask(suggestion) }, suggestion))));
    }
    wrapper.appendChild(h('div', { class: 'msg__meta' },
      `${response.answer_language?.toUpperCase() || ''} · `
      + `${Math.round(response.latency?.total_ms || 0)} ms · `
      + dateTimeIST(response.generated_at)));
    return wrapper;
  }

  function errorCard(turn) {
    return h('div', { class: 'card err' },
      h('div', { class: 'card__head' },
        h('div', { class: 'card__title' },
          h('span', { 'aria-hidden': 'true' }, ICON.warn), ' ', t('cannotVerify'))),
      h('div', { style: { padding: '0 16px 16px' } },
        h('p', {}, turn.error),
        turn.cachedAvailable
          ? h('button', { class: 'btn btn--sm', type: 'button',
                          onclick: () => showCached(turn) }, t('showLast'))
          : null,
        h('button', { class: 'btn btn--sm btn--ghost', type: 'button',
                      onclick: () => ask(turn.query) }, t('retry'))));
  }

  function showCached(turn) {
    const cached = recall(turn.query, ctx());
    if (!cached) { toast('Nothing saved for that question yet.'); return; }
    state.turns = state.turns.map((existing) => existing === turn
      ? { ...existing, response: cached.response, error: null, cached }
      : existing);
    update({ turns: state.turns });
    renderThread();
  }

  // ---- asking ------------------------------------------------------------
  const ctx = () => ({ mode: state.mode, lang: state.lang, location: state.location });

  async function submit() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    await ask(text);
  }

  async function ask(text) {
    const turn = { query: text, response: null, error: null, at: Date.now() };
    addTurn(turn);
    // Full re-render, not just the thread: on the first question the surface
    // switches from the home block to the conversation, and the thread node is
    // not in the document until it does.
    render();

    const progress = progressPanel(getLang());
    thread.appendChild(h('div', { class: 'msg' }, progress));
    thread.scrollTop = thread.scrollHeight;
    announce(t('thinking'));

    const started = performance.now();
    const payload = {
      query: text,
      session_id: state.sessionId || undefined,
      language: state.lang === 'en' ? undefined : state.lang,
      activity: mode().activity,
      vessel: mode().vessel,
      low_bandwidth: state.lowBandwidth,
      include_trace: true,
    };
    if (state.location) {
      payload.lat = state.location.lat;
      payload.lon = state.location.lon;
    }

    try {
      const response = await api.query(payload);
      observe({ ok: true, ms: Math.round(performance.now() - started) });
      progress.stop();
      update({ sessionId: response.session_id });
      remember(text, ctx(), response);
      state.turns = state.turns.map((existing) =>
        existing === turn ? { ...existing, response } : existing);
      update({ turns: state.turns, lastAnswerAt: Date.now() });
      renderThread();
      announceRisk(response);
    } catch (err) {
      progress.stop();
      observe({ ok: false, kind: err instanceof ApiError ? err.kind : 'error' });
      const cached = recall(text, ctx());
      state.turns = state.turns.map((existing) => existing === turn
        ? { ...existing, error: err.message, cachedAvailable: Boolean(cached) }
        : existing);
      update({ turns: state.turns });
      renderThread();
    }
  }

  function announceRisk(response) {
    if (!response.risk) { announce('Answer ready'); return; }
    const level = response.risk.risk_level;
    announce(`Marine risk ${level.replace('_', ' ')}. ${response.answer.split('\n')[1] || ''}`);
    if (state.speakAnswers && voice.canSpeakAloud()) {
      voice.speak(response.answer.split('\n').slice(0, 3).join('. '), state.lang);
    }
  }

  // ---- voice -------------------------------------------------------------
  let recogniser = null;
  function startVoice() {
    if (recogniser) { recogniser.stop(); recogniser = null; return; }
    recogniser = voice.createRecogniser(state.lang);
    if (!recogniser) { toast('Speech input is not available in this browser.'); return; }
    micButton.dataset.listening = 'true';
    input.placeholder = t('listening');
    recogniser.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((r) => r[0].transcript).join(' ').trim();
      input.value = transcript;
      if (event.results[event.results.length - 1].isFinal) {
        stopVoice();
        if (transcript) ask(transcript);
      }
    };
    recogniser.onerror = () => { stopVoice(); toast('Could not hear that. Try typing.'); };
    recogniser.onend = () => stopVoice();
    try { recogniser.start(); } catch { stopVoice(); }
  }

  function stopVoice() {
    if (micButton) delete micButton.dataset.listening;
    input.placeholder = t('askPlaceholder');
    recogniser = null;
  }

  // ---- home content ------------------------------------------------------
  function homeBlock() {
    const placeName = state.location?.label || 'Kochi';
    const quickKeys = mode().quick;
    const grid = h('div', { class: 'quickgrid' }, ...quickKeys.map((key) => {
      const item = QUICK[key];
      if (!item) return null;
      const label = t(item.key);
      return h('button', {
        class: 'quick', type: 'button',
        onclick: () => {
          if (item.view) { app.go(item.view); return; }
          const template = item.query[state.lang] || item.query.en;
          ask(template.replace('{place}', placeName));
        },
      },
        h('span', { class: 'quick__icon', 'aria-hidden': 'true' }, ICON[item.icon]),
        h('span', { class: 'quick__label' }, label),
        h('span', { class: 'quick__hint' },
          item.view ? '' : (state.location ? t('usingLocation') : placeName)));
    }));

    const saved = recent(3);
    return h('div', { class: 'stack' },
      h('div', { class: 'hero' },
        h('div', { class: 'hero__eyebrow' }, 'ORCA · Marine Intelligence'),
        h('h1', { class: 'hero__title' }, t('askTitle')),
        h('p', { class: 'hero__sub' }, t('tagline'))),
      h('div', { class: 'section-title' }, t('quickTitle')),
      grid,
      h('div', { class: 'chips' }, ...(t('examples') || []).slice(0, 2).map((example) =>
        h('button', { class: 'chip', type: 'button', onclick: () => ask(example) },
          h('span', { 'aria-hidden': 'true' }, ICON.search), ' ',
          example.length > 46 ? `${example.slice(0, 44)}…` : example))),
      saved.length
        ? h('div', { class: 'stack stack--tight' },
            h('div', { class: 'section-title' }, t('cachedAnswer')),
            ...saved.map((item) =>
              h('button', { class: 'quick quick--wide', type: 'button',
                            onclick: () => ask(item.query) },
                h('span', { class: 'quick__icon', 'aria-hidden': 'true' }, ICON.time),
                h('span', { class: 'grow' },
                  h('span', { class: 'quick__label' },
                    item.query.length > 52 ? `${item.query.slice(0, 50)}…` : item.query),
                  h('span', { class: 'quick__hint' },
                    `${t('lastUpdated')} ${dateTimeIST(new Date(item.savedAt).toISOString())}`)))))
        : null);
  }

  function render() {
    while (container.firstChild) container.removeChild(container.firstChild);
    if (state.turns.length) {
      container.appendChild(h('div', { class: 'spread' },
        h('div', { class: 'section-title' },
          h('span', { 'aria-hidden': 'true' }, ICON.boat), ' ORCA'),
        h('button', { class: 'btn btn--sm btn--ghost', type: 'button',
                      onclick: () => { resetConversation(); render(); } }, 'New question')));
      container.appendChild(thread);
      renderThread();
    } else {
      container.appendChild(homeBlock());
    }
    container.appendChild(askbox);
    
    // Trigger GSAP entrance animations
    requestAnimationFrame(() => {
      if (window.gsap && !state.lowBandwidth) {
        if (!state.turns.length) {
          window.gsap.fromTo(container.querySelectorAll('.hero, .section-title, .quick, .chip'), 
            { y: 30, opacity: 0, scale: 0.95, filter: 'blur(8px)' }, 
            { y: 0, opacity: 1, scale: 1, filter: 'blur(0px)', duration: 0.8, stagger: 0.08, ease: 'expo.out' });
        }
        window.gsap.fromTo(askbox, 
          { y: 30, opacity: 0, scale: 0.98, filter: 'blur(4px)' }, 
          { y: 0, opacity: 1, scale: 1, filter: 'blur(0px)', duration: 0.8, delay: state.turns.length ? 0 : 0.4, ease: 'expo.out' });
      }
    });
  }

  render();
  container.ask = ask;
  container.refresh = render;
  return container;
}

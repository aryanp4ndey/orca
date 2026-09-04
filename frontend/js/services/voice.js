/**
 * Speech input.
 *
 * Web Speech API where the browser genuinely has it, and nothing that pretends
 * otherwise where it does not. `isAvailable()` is checked before the microphone
 * button is rendered at all - a microphone that does nothing is worse than no
 * microphone, particularly for a user who cannot easily type.
 */

const Recognition = typeof window !== 'undefined'
  ? (window.SpeechRecognition || window.webkitSpeechRecognition)
  : null;

const LOCALE = { en: 'en-IN', hi: 'hi-IN', ml: 'ml-IN', ta: 'ta-IN' };

export function isAvailable() {
  return Boolean(Recognition);
}

export function createRecogniser(lang = 'en') {
  if (!Recognition) return null;
  const recogniser = new Recognition();
  recogniser.lang = LOCALE[lang] || 'en-IN';
  recogniser.interimResults = true;
  recogniser.continuous = false;
  recogniser.maxAlternatives = 1;
  return recogniser;
}

/** Speak an answer aloud. Optional by design: it fails silently if absent. */
export function speak(text, lang = 'en') {
  try {
    if (!('speechSynthesis' in window)) return false;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = LOCALE[lang] || 'en-IN';
    utterance.rate = 0.95;
    window.speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

export function stopSpeaking() {
  try { window.speechSynthesis?.cancel(); } catch { /* ignore */ }
}

export const canSpeakAloud = () =>
  typeof window !== 'undefined' && 'speechSynthesis' in window;

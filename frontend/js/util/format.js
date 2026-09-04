/** Formatting. All display times are IST, because the users are on the Indian coast. */

const IST = 'Asia/Kolkata';

export function parseTime(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeIST(value, opts = {}) {
  const d = parseTime(value);
  if (!d) return '—';
  return d.toLocaleTimeString('en-IN', {
    timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: false, ...opts,
  });
}

export function dateTimeIST(value) {
  const d = parseTime(value);
  if (!d) return '—';
  return d.toLocaleString('en-IN', {
    timeZone: IST, day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
}

/** "tomorrow 07:00" style phrasing, relative to now, in IST. */
export function whenPhrase(value, lang = 'en') {
  const d = parseTime(value);
  if (!d) return '';
  const dayKey = (x) => x.toLocaleDateString('en-CA', { timeZone: IST });
  const now = new Date();
  const diff = (new Date(dayKey(d)) - new Date(dayKey(now))) / 86400000;
  const words = {
    en: { '-1': 'yesterday', 0: 'today', 1: 'tomorrow', 2: 'day after' },
    hi: { '-1': 'कल', 0: 'आज', 1: 'कल', 2: 'परसों' },
  };
  const word = (words[lang] || words.en)[String(diff)];
  const clock = timeIST(value);
  if (word) return `${word} ${clock}`;
  return `${d.toLocaleDateString('en-IN', { timeZone: IST, day: '2-digit', month: 'short' })} ${clock}`;
}

export function relativeAge(seconds, lang = 'en') {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const s = Math.max(0, Math.round(seconds));
  if (s < 90) return lang === 'hi' ? 'अभी' : 'just now';
  const m = Math.round(s / 60);
  if (m < 90) return lang === 'hi' ? `${m} मिनट पहले` : `${m} min ago`;
  const hrs = Math.round(m / 60);
  if (hrs < 36) return lang === 'hi' ? `${hrs} घंटे पहले` : `${hrs} h ago`;
  const days = Math.round(hrs / 24);
  return lang === 'hi' ? `${days} दिन पहले` : `${days} d ago`;
}

/** Trim a float for display without lying about precision. */
export function num(value, unit = '') {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value !== 'number') return String(value);
  const abs = Math.abs(value);
  const decimals = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  const text = Number(value.toFixed(decimals)).toString();
  return unit ? `${text} ${unit}` : text;
}

export function coords(point) {
  if (!point) return '—';
  const lat = Number(point.lat), lon = Number(point.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return '—';
  return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? 'N' : 'S'}, ` +
         `${Math.abs(lon).toFixed(3)}° ${lon >= 0 ? 'E' : 'W'}`;
}

export function titleCase(text) {
  return String(text || '').replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export const VARIABLE_ICON = {
  wind_speed_10m: '🌬', wind_gust_10m: '💨', wind_direction_10m: '🧭',
  wave_height_significant: '🌊', wave_period: '〰️', wave_direction: '🧭',
  swell_height: '〰️', swell_period: '〰️',
  precipitation: '🌧', visibility: '👁', cloud_cover: '☁️',
  temperature_2m: '🌡', cape: '⛈', thunderstorm_probability: '⛈',
  sea_surface_temperature: '🌡', current_speed: '🌀', current_direction: '🧭',
  chlorophyll_a: '🟢', distance_to_coast_km: '📏', maritime_band: '🗺',
};

export const icon = (variable) => VARIABLE_ICON[variable] || '•';

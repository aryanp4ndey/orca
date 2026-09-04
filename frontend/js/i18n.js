/**
 * Interface strings.
 *
 * The *answer* is translated by the backend - the message catalogue lives there
 * and the internal representation is language-independent. This file only
 * covers the chrome around it, so adding a language here is adding a column,
 * exactly as it is on the server.
 */

const STRINGS = {
  en: {
    tagline: 'Ask once. Understand the ocean.',
    askTitle: 'Ask about the sea.',
    askPlaceholder: 'Ask about the sea…',
    send: 'Ask',
    speak: 'Speak',
    listening: 'Listening…',
    useLocation: 'Use my location',
    chooseLocation: 'Choose a place',
    locating: 'Finding your position…',
    usingLocation: 'Using your location',
    quickTitle: 'Ask in one tap',
    quickFishing: 'Fishing safety',
    quickSea: 'Sea status',
    quickWarnings: 'Warnings',
    quickPFZ: 'Fishing zones',
    home: 'Ask',
    map: 'Map',
    alerts: 'Alerts',
    more: 'More',
    why: 'Why this result?',
    viewEvidence: 'View evidence',
    viewMap: 'View map',
    howDecided: 'How ORCA decided',
    technical: 'Technical details',
    evidence: 'Evidence',
    sources: 'Sources',
    retrieved: 'Retrieved',
    forecast: 'Forecast for',
    issued: 'Issued',
    freshness: 'Freshness',
    demoData: 'DEMO DATA',
    demoNote: 'Values come from ORCA’s built-in demonstration dataset, not a live feed.',
    online: 'Online',
    degraded: 'Weak connection',
    offline: 'Offline',
    lastUpdated: 'Last updated',
    cachedAnswer: 'Saved answer',
    cannotVerify: 'Current marine conditions could not be verified.',
    showLast: 'Show last available information',
    retry: 'Try again',
    thinking: 'Understanding your request…',
    compare: 'Compare',
    compareTimes: 'Compare two times',
    route: 'Route risk',
    findPFZ: 'Find nearest fishing zone',
    settings: 'Settings',
    language: 'Language',
    mode: 'Who is asking',
    lowBandwidth: 'Low-bandwidth mode',
    lowBandwidthNote: 'Less map detail, no animation, text first.',
    modes: {
      fisher: { name: 'Fisher', desc: 'Simple, safety-first answers' },
      researcher: { name: 'Researcher', desc: 'Variables, comparisons, metadata' },
      disaster: { name: 'Disaster management', desc: 'Hazards, areas, freshness' },
      maritime: { name: 'Maritime', desc: 'Routes, corridors, boundaries' },
    },
    examples: [
      'Is it safe to go fishing from Kochi tomorrow at 7 AM?',
      'What is the sea condition near Kochi?',
      'Where is the nearest Potential Fishing Zone today?',
      'Are there any cyclone or lightning warnings near my location?',
    ],
    disclaimer: 'Decision support, not a certified navigation or safety system.',
  },

  hi: {
    tagline: 'एक बार पूछिए। समुद्र को समझिए।',
    askTitle: 'समुद्र के बारे में पूछिए।',
    askPlaceholder: 'समुद्र के बारे में पूछिए…',
    send: 'पूछें',
    speak: 'बोलें',
    listening: 'सुन रहे हैं…',
    useLocation: 'मेरी लोकेशन लें',
    chooseLocation: 'जगह चुनें',
    locating: 'आपकी स्थिति देख रहे हैं…',
    usingLocation: 'आपकी लोकेशन का उपयोग',
    quickTitle: 'एक टैप में पूछें',
    quickFishing: 'मछली पकड़ना सुरक्षित?',
    quickSea: 'समुद्र की स्थिति',
    quickWarnings: 'चेतावनियाँ',
    quickPFZ: 'मछली क्षेत्र',
    home: 'पूछें',
    map: 'नक्शा',
    alerts: 'चेतावनी',
    more: 'और',
    why: 'यह परिणाम क्यों?',
    viewEvidence: 'प्रमाण देखें',
    viewMap: 'नक्शा देखें',
    howDecided: 'ORCA ने कैसे तय किया',
    technical: 'तकनीकी विवरण',
    evidence: 'प्रमाण',
    sources: 'स्रोत',
    retrieved: 'प्राप्त',
    forecast: 'पूर्वानुमान',
    issued: 'जारी',
    freshness: 'नवीनता',
    demoData: 'डेमो डेटा',
    demoNote: 'ये मान ORCA के डेमो डेटा से हैं, किसी लाइव स्रोत से नहीं।',
    online: 'ऑनलाइन',
    degraded: 'कमज़ोर कनेक्शन',
    offline: 'ऑफ़लाइन',
    lastUpdated: 'अंतिम अपडेट',
    cachedAnswer: 'सहेजा गया उत्तर',
    cannotVerify: 'मौजूदा समुद्री स्थिति की पुष्टि नहीं हो सकी।',
    showLast: 'पिछली उपलब्ध जानकारी दिखाएँ',
    retry: 'फिर कोशिश करें',
    thinking: 'आपका सवाल समझ रहे हैं…',
    compare: 'तुलना',
    compareTimes: 'दो समय की तुलना',
    route: 'मार्ग जोखिम',
    findPFZ: 'निकटतम मछली क्षेत्र',
    settings: 'सेटिंग्स',
    language: 'भाषा',
    mode: 'कौन पूछ रहा है',
    lowBandwidth: 'कम-बैंडविड्थ मोड',
    lowBandwidthNote: 'कम नक्शा विवरण, कोई एनिमेशन नहीं, पहले टेक्स्ट।',
    modes: {
      fisher: { name: 'मछुआरा', desc: 'सरल, सुरक्षा-पहले उत्तर' },
      researcher: { name: 'शोधकर्ता', desc: 'चर, तुलना, मेटाडेटा' },
      disaster: { name: 'आपदा प्रबंधन', desc: 'खतरे, क्षेत्र, नवीनता' },
      maritime: { name: 'समुद्री', desc: 'मार्ग, गलियारे, सीमाएँ' },
    },
    examples: [
      'क्या कल सुबह 7 बजे कोच्चि से मछली पकड़ने जाना सुरक्षित है?',
      'कोच्चि के पास समुद्र की स्थिति क्या है?',
      'आज निकटतम मछली क्षेत्र कहाँ है?',
      'क्या मेरे पास कोई चक्रवात या बिजली की चेतावनी है?',
    ],
    disclaimer: 'निर्णय सहायता, कोई प्रमाणित नौवहन या सुरक्षा प्रणाली नहीं।',
  },

  ml: {
    tagline: 'ഒരിക്കൽ ചോദിക്കൂ. കടലിനെ അറിയൂ.',
    askTitle: 'കടലിനെക്കുറിച്ച് ചോദിക്കൂ.',
    askPlaceholder: 'കടലിനെക്കുറിച്ച് ചോദിക്കൂ…',
    send: 'ചോദിക്കൂ',
    speak: 'സംസാരിക്കൂ',
    useLocation: 'എന്റെ സ്ഥാനം',
    chooseLocation: 'സ്ഥലം തിരഞ്ഞെടുക്കൂ',
    quickTitle: 'ഒറ്റ ടാപ്പിൽ ചോദിക്കൂ',
    quickFishing: 'മീൻപിടിത്തം സുരക്ഷിതമോ?',
    quickSea: 'കടലിന്റെ സ്ഥിതി',
    quickWarnings: 'മുന്നറിയിപ്പുകൾ',
    quickPFZ: 'മത്സ്യബന്ധന മേഖല',
    why: 'എന്തുകൊണ്ട് ഈ ഫലം?',
    viewEvidence: 'തെളിവ് കാണുക',
    viewMap: 'ഭൂപടം',
    demoData: 'ഡെമോ ഡാറ്റ',
    examples: [
      'നാളെ രാവിലെ 7 മണിക്ക് കൊച്ചിയിൽ നിന്ന് മീൻപിടിക്കാൻ പോകുന്നത് സുരക്ഷിതമാണോ?',
      'കൊച്ചിക്കടുത്ത് കടലിന്റെ സ്ഥിതി എന്താണ്?',
    ],
  },

  ta: {
    tagline: 'ஒருமுறை கேளுங்கள். கடலைப் புரிந்துகொள்ளுங்கள்.',
    askTitle: 'கடலைப் பற்றி கேளுங்கள்.',
    askPlaceholder: 'கடலைப் பற்றி கேளுங்கள்…',
    send: 'கேள்',
    speak: 'பேசு',
    useLocation: 'என் இருப்பிடம்',
    chooseLocation: 'இடத்தைத் தேர்ந்தெடு',
    quickTitle: 'ஒரே தட்டலில் கேளுங்கள்',
    quickFishing: 'மீன்பிடி பாதுகாப்பானதா?',
    quickSea: 'கடல் நிலை',
    quickWarnings: 'எச்சரிக்கைகள்',
    quickPFZ: 'மீன்பிடி மண்டலம்',
    why: 'ஏன் இந்த முடிவு?',
    viewEvidence: 'ஆதாரம்',
    viewMap: 'வரைபடம்',
    demoData: 'டெமோ தரவு',
    examples: [
      'நாளை காலை 7 மணிக்கு சென்னையிலிருந்து மீன்பிடிக்கச் செல்வது பாதுகாப்பானதா?',
      'சென்னை அருகே கடல் நிலை என்ன?',
    ],
  },
};

export const LANGUAGES = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'hi', label: 'Hindi', native: 'हिन्दी' },
  { code: 'ml', label: 'Malayalam', native: 'മലയാളം' },
  { code: 'ta', label: 'Tamil', native: 'தமிழ்' },
];

let current = 'en';

export function setLang(code) {
  current = STRINGS[code] ? code : 'en';
  if (typeof document !== 'undefined') document.documentElement.lang = current;
}

export const getLang = () => current;

/** Look up a string, falling back to English so a partial translation never
 *  produces a blank label. */
export function t(key) {
  const walk = (obj) => key.split('.').reduce((o, k) => (o ? o[k] : undefined), obj);
  const value = walk(STRINGS[current]);
  if (value !== undefined && value !== null) return value;
  const fallback = walk(STRINGS.en);
  return fallback !== undefined ? fallback : key;
}

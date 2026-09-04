"""Message catalogue.

The internal representation is language-independent, so the *only* place a
language appears in an answer is here.  Adding Bengali or Telugu means adding a
column to these tables - no logic changes, no new prompts, no new agent.

Every template is written to be read aloud, because the target user may be
listening rather than reading, and to be understandable without knowing what an
agent or a provider is.
"""

from __future__ import annotations

from app.schemas.common import Language

FALLBACK = Language.EN

CATALOG: dict[str, dict[str, str]] = {
    # ---- risk verdicts ----------------------------------------------------
    "risk.LOW": {
        "en": "Conditions look manageable.",
        "hi": "स्थिति सामान्य लग रही है।",
        "ml": "സ്ഥിതി പൊതുവേ അനുകൂലമാണ്.",
        "ta": "நிலைமை பொதுவாக சாதகமாக உள்ளது.",
    },
    "risk.MODERATE": {
        "en": "Go only if you are prepared. Conditions are borderline.",
        "hi": "सावधानी से ही जाएँ। स्थिति सामान्य से कुछ कठिन है।",
        "ml": "ജാഗ്രതയോടെ മാത്രം പോകുക. സ്ഥിതി അൽപ്പം പ്രതികൂലമാണ്.",
        "ta": "எச்சரிக்கையுடன் மட்டுமே செல்லுங்கள். நிலைமை சற்று கடினமாக உள்ளது.",
    },
    "risk.HIGH": {
        "en": "Not advisable. Conditions are dangerous for this activity.",
        "hi": "जाना ठीक नहीं है। स्थिति खतरनाक है।",
        "ml": "പോകാൻ ഉചിതമല്ല. സ്ഥിതി അപകടകരമാണ്.",
        "ta": "செல்வது உகந்ததல்ல. நிலைமை ஆபத்தானது.",
    },
    "risk.CRITICAL": {
        "en": "Do not go out. Conditions are severe.",
        "hi": "बिलकुल न जाएँ। स्थिति बहुत खतरनाक है।",
        "ml": "പുറത്തുപോകരുത്. സ്ഥിതി അതീവ ഗുരുതരമാണ്.",
        "ta": "கடலுக்குச் செல்ல வேண்டாம். நிலைமை மிகவும் ஆபத்தானது.",
    },
    "risk.INSUFFICIENT_DATA": {
        "en": "ORCA cannot tell you whether this is safe - the data it needs is missing or too old. Please treat this as unknown, not as safe.",
        "hi": "ORCA यह नहीं बता सकता कि यह सुरक्षित है या नहीं - ज़रूरी जानकारी नहीं मिली या बहुत पुरानी है। इसे 'पता नहीं' समझें, 'सुरक्षित' नहीं।",
        "ml": "ഇത് സുരക്ഷിതമാണോ എന്ന് ORCA-യ്ക്ക് പറയാനാവില്ല - ആവശ്യമായ വിവരം ലഭ്യമല്ല അല്ലെങ്കിൽ പഴയതാണ്. ഇത് 'അറിയില്ല' എന്നു കരുതുക, 'സുരക്ഷിതം' എന്നല്ല.",
        "ta": "இது பாதுகாப்பானதா என்று ORCA கூற முடியாது - தேவையான தரவு இல்லை அல்லது மிகவும் பழையது. இதை 'தெரியவில்லை' என்று கருதுங்கள், 'பாதுகாப்பானது' என்று அல்ல.",
    },
    # ---- framing ----------------------------------------------------------
    "answer.for": {
        "en": "For {activity} from {place}, {when}:",
        "hi": "{place} से {activity} के लिए, {when}:",
        "ml": "{place}-ൽ നിന്ന് {activity}, {when}:",
        "ta": "{place} இலிருந்து {activity}, {when}:",
    },
    "answer.because": {
        "en": "Main reasons:",
        "hi": "मुख्य कारण:",
        "ml": "പ്രധാന കാരണങ്ങൾ:",
        "ta": "முக்கிய காரணங்கள்:",
    },
    "answer.sea_state": {
        "en": "Sea state near {place}, {when}:",
        "hi": "{place} के पास समुद्र की स्थिति, {when}:",
        "ml": "{place}-നടുത്ത് കടലിന്റെ സ്ഥിതി, {when}:",
        "ta": "{place} அருகே கடல் நிலை, {when}:",
    },
    "answer.weather": {
        "en": "Marine weather near {place}, {when}:",
        "hi": "{place} के पास समुद्री मौसम, {when}:",
        "ml": "{place}-നടുത്ത് കടൽ കാലാവസ്ഥ, {when}:",
        "ta": "{place} அருகே கடல் வானிலை, {when}:",
    },
    "answer.no_warnings": {
        "en": "No warning was found in force for this area in the sources ORCA could reach.",
        "hi": "जिन स्रोतों तक ORCA पहुँच सका, उनमें इस क्षेत्र के लिए कोई चेतावनी नहीं मिली।",
        "ml": "ORCA-യ്ക്ക് ലഭ്യമായ ഉറവിടങ്ങളിൽ ഈ പ്രദേശത്തിന് മുന്നറിയിപ്പൊന്നും കണ്ടെത്തിയില്ല.",
        "ta": "ORCA அணுகக்கூடிய ஆதாரங்களில் இப்பகுதிக்கு எச்சரிக்கை எதுவும் இல்லை.",
    },
    "answer.warnings_in_force": {
        "en": "Warnings in force:",
        "hi": "लागू चेतावनियाँ:",
        "ml": "പ്രാബല്യത്തിലുള്ള മുന്നറിയിപ്പുകൾ:",
        "ta": "அமலில் உள்ள எச்சரிக்கைகள்:",
    },
    "answer.pfz_nearest": {
        "en": "Nearest potential fishing zone: {distance} km {compass} of {place}, valid until {valid_to}.",
        "hi": "निकटतम संभावित मछली क्षेत्र: {place} से {distance} किमी {compass}, {valid_to} तक मान्य।",
        "ml": "അടുത്തുള്ള മത്സ്യബന്ധന മേഖല: {place}-ൽ നിന്ന് {distance} കി.മീ {compass}, {valid_to} വരെ സാധുവാണ്.",
        "ta": "அருகிலுள்ள மீன்பிடி மண்டலம்: {place} இலிருந்து {distance} கி.மீ {compass}, {valid_to} வரை செல்லுபடியாகும்.",
    },
    "answer.pfz_none": {
        "en": "No potential fishing zone advisory was available for this area and date.",
        "hi": "इस क्षेत्र और तारीख के लिए कोई संभावित मछली क्षेत्र सलाह उपलब्ध नहीं थी।",
        "ml": "ഈ പ്രദേശത്തിനും തീയതിക്കും മത്സ്യബന്ധന മേഖലാ ഉപദേശം ലഭ്യമായിരുന്നില്ല.",
        "ta": "இப்பகுதிக்கும் தேதிக்கும் மீன்பிடி மண்டல ஆலோசனை கிடைக்கவில்லை.",
    },
    "answer.avoid": {
        "en": "Areas to keep clear of near {place}:",
        "hi": "{place} के पास जिन क्षेत्रों से बचें:",
        "ml": "{place}-നടുത്ത് ഒഴിവാക്കേണ്ട പ്രദേശങ്ങൾ:",
        "ta": "{place} அருகே தவிர்க்க வேண்டிய பகுதிகள்:",
    },
    "answer.route": {
        "en": "Passage from {start} to {end}: {distance} km, about {hours} hours at {speed} knots.",
        "hi": "{start} से {end} तक का रास्ता: {distance} किमी, लगभग {hours} घंटे {speed} नॉट पर।",
        "ml": "{start} മുതൽ {end} വരെ: {distance} കി.മീ, {speed} നോട്ടിൽ ഏകദേശം {hours} മണിക്കൂർ.",
        "ta": "{start} முதல் {end} வரை: {distance} கி.மீ, {speed} நாட்டில் சுமார் {hours} மணி நேரம்.",
    },
    "answer.no_location": {
        "en": "Which place should ORCA check? Tell me a coastal town or harbour, or share your location.",
        "hi": "ORCA किस जगह की जानकारी देखे? कोई तटीय शहर या बंदरगाह बताइए, या अपनी लोकेशन साझा कीजिए।",
        "ml": "ഏത് സ്ഥലമാണ് പരിശോധിക്കേണ്ടത്? ഒരു തീരദേശ പട്ടണമോ തുറമുഖമോ പറയുക, അല്ലെങ്കിൽ നിങ്ങളുടെ സ്ഥാനം പങ്കിടുക.",
        "ta": "எந்த இடத்தைச் சரிபார்க்க வேண்டும்? ஒரு கடலோர ஊர் அல்லது துறைமுகத்தைச் சொல்லுங்கள், அல்லது உங்கள் இருப்பிடத்தைப் பகிருங்கள்.",
    },
    "answer.clarify": {
        "en": "ORCA is not sure what you are asking. You can ask about sea safety, sea conditions, marine weather, fishing zones, warnings, or a passage between two places.",
        "hi": "ORCA आपका सवाल ठीक से समझ नहीं पाया। आप समुद्र में सुरक्षा, समुद्र की स्थिति, मौसम, मछली क्षेत्र, चेतावनी, या दो जगहों के बीच रास्ते के बारे में पूछ सकते हैं।",
        "ml": "ചോദ്യം വ്യക്തമല്ല. കടൽ സുരക്ഷ, കടൽ സ്ഥിതി, കാലാവസ്ഥ, മത്സ്യബന്ധന മേഖല, മുന്നറിയിപ്പുകൾ എന്നിവയെക്കുറിച്ച് ചോദിക്കാം.",
        "ta": "கேள்வி தெளிவாக இல்லை. கடல் பாதுகாப்பு, கடல் நிலை, வானிலை, மீன்பிடி மண்டலம், எச்சரிக்கைகள் பற்றி கேட்கலாம்.",
    },
    "answer.greeting": {
        "en": "I am ORCA. Ask me whether it is safe to go out, what the sea is doing, where the fishing zones are, or whether there is a warning for your coast.",
        "hi": "मैं ORCA हूँ। पूछिए कि समुद्र में जाना सुरक्षित है या नहीं, समुद्र की स्थिति कैसी है, मछली क्षेत्र कहाँ हैं, या आपके तट के लिए कोई चेतावनी है।",
        "ml": "ഞാൻ ORCA. കടലിൽ പോകുന്നത് സുരക്ഷിതമാണോ, കടലിന്റെ സ്ഥിതി എന്താണ്, മത്സ്യബന്ധന മേഖലകൾ എവിടെയാണ് എന്നൊക്കെ ചോദിക്കാം.",
        "ta": "நான் ORCA. கடலுக்குச் செல்வது பாதுகாப்பானதா, கடல் நிலை என்ன, மீன்பிடி மண்டலங்கள் எங்கே என்று கேட்கலாம்.",
    },
    # ---- provenance and caveats -------------------------------------------
    "note.sources": {
        "en": "Based on {sources}, retrieved {retrieved}.",
        "hi": "{sources} के आधार पर, {retrieved} को प्राप्त।",
        "ml": "{sources} അടിസ്ഥാനമാക്കി, {retrieved}-ന് ലഭിച്ചത്.",
        "ta": "{sources} அடிப்படையில், {retrieved} இல் பெறப்பட்டது.",
    },
    "note.demo": {
        "en": "DEMO MODE: these values come from ORCA's built-in demonstration dataset, not from a live feed.",
        "hi": "डेमो मोड: ये मान ORCA के अंतर्निहित डेमो डेटा से हैं, किसी लाइव फ़ीड से नहीं।",
        "ml": "ഡെമോ മോഡ്: ഈ മൂല്യങ്ങൾ ORCA-യുടെ ഡെമോ ഡാറ്റയിൽ നിന്നാണ്, തത്സമയ ഉറവിടത്തിൽ നിന്നല്ല.",
        "ta": "டெமோ பயன்முறை: இந்த மதிப்புகள் ORCA இன் டெமோ தரவிலிருந்து வந்தவை, நேரடி ஊட்டத்திலிருந்து அல்ல.",
    },
    "note.stale": {
        "en": "Some readings are older than they should be. Check the current official advisory before you go.",
        "hi": "कुछ जानकारी अपेक्षा से पुरानी है। जाने से पहले मौजूदा आधिकारिक सलाह देखें।",
        "ml": "ചില വിവരങ്ങൾ പഴയതാണ്. പോകുന്നതിനു മുൻപ് ഔദ്യോഗിക ഉപദേശം പരിശോധിക്കുക.",
        "ta": "சில தரவுகள் பழையவை. செல்வதற்கு முன் அதிகாரப்பூர்வ ஆலோசனையைப் பாருங்கள்.",
    },
    "note.source_down": {
        "en": "{source} could not be reached, so this answer is less certain than usual.",
        "hi": "{source} तक नहीं पहुँचा जा सका, इसलिए यह उत्तर सामान्य से कम निश्चित है।",
        "ml": "{source}-ലേക്ക് എത്താനായില്ല, അതിനാൽ ഈ ഉത്തരം സാധാരണയേക്കാൾ ഉറപ്പു കുറവാണ്.",
        "ta": "{source} ஐ அணுக முடியவில்லை, எனவே இந்த பதில் வழக்கத்தை விட உறுதி குறைவு.",
    },
    "note.conflict": {
        "en": "Sources disagree on {variable}; ORCA used the {winner} value and lowered its confidence.",
        "hi": "{variable} पर स्रोत असहमत हैं; ORCA ने {winner} का मान लिया और भरोसा कम किया।",
        "ml": "{variable} സംബന്ധിച്ച് ഉറവിടങ്ങൾ യോജിക്കുന്നില്ല; ORCA {winner} മൂല്യം ഉപയോഗിച്ചു.",
        "ta": "{variable} குறித்து ஆதாரங்கள் ஒத்துப்போகவில்லை; ORCA {winner} மதிப்பைப் பயன்படுத்தியது.",
    },
    "note.disclaimer": {
        "en": "ORCA is a decision-support prototype, not a certified navigation or maritime-safety system. Always check the official IMD / INCOIS advisory and your local authority before going to sea.",
        "hi": "ORCA एक निर्णय-सहायक प्रोटोटाइप है, कोई प्रमाणित नौवहन या समुद्री सुरक्षा प्रणाली नहीं। समुद्र में जाने से पहले हमेशा आधिकारिक IMD / INCOIS सलाह और स्थानीय प्राधिकरण से जाँच करें।",
        "ml": "ORCA ഒരു തീരുമാന-സഹായ പ്രോട്ടോടൈപ്പ് ആണ്, സാക്ഷ്യപ്പെടുത്തിയ നാവിഗേഷൻ സംവിധാനമല്ല. കടലിൽ പോകുന്നതിനു മുൻപ് ഔദ്യോഗിക IMD / INCOIS ഉപദേശം പരിശോധിക്കുക.",
        "ta": "ORCA ஒரு முடிவு-ஆதரவு முன்மாதிரி, சான்றளிக்கப்பட்ட வழிசெலுத்தல் அமைப்பு அல்ல. கடலுக்குச் செல்வதற்கு முன் அதிகாரப்பூர்வ IMD / INCOIS ஆலோசனையைப் பாருங்கள்.",
    },
    # ---- variable labels --------------------------------------------------
    "var.wave_height_significant": {"en": "Wave height", "hi": "लहर की ऊँचाई", "ml": "തിരമാലയുടെ ഉയരം", "ta": "அலை உயரம்"},
    "var.wind_speed_10m": {"en": "Wind", "hi": "हवा", "ml": "കാറ്റ്", "ta": "காற்று"},
    "var.wind_gust_10m": {"en": "Gusts", "hi": "झोंके", "ml": "കാറ്റിന്റെ ശക്തി", "ta": "காற்று வேகம்"},
    "var.swell_height": {"en": "Swell", "hi": "स्वेल", "ml": "സ്വെൽ", "ta": "வீக்க அலை"},
    "var.visibility": {"en": "Visibility", "hi": "दृश्यता", "ml": "ദൃശ്യപരത", "ta": "தெரிவுநிலை"},
    "var.precipitation": {"en": "Rain", "hi": "बारिश", "ml": "മഴ", "ta": "மழை"},
    "var.thunderstorm_probability": {"en": "Thunderstorm chance", "hi": "तूफ़ान की संभावना", "ml": "ഇടിമിന്നൽ സാധ്യത", "ta": "இடியுடன் மழை வாய்ப்பு"},
    "var.sea_surface_temperature": {"en": "Sea temperature", "hi": "समुद्र का तापमान", "ml": "കടലിന്റെ താപനില", "ta": "கடல் வெப்பநிலை"},
    "var.current_speed": {"en": "Current", "hi": "धारा", "ml": "പ്രവാഹം", "ta": "நீரோட்டம்"},
    "var.wave_period": {"en": "Wave period", "hi": "लहर अंतराल", "ml": "തിരമാല ഇടവേള", "ta": "அலை இடைவெளி"},
    # ---- activities -------------------------------------------------------
    "act.fishing_small_boat": {"en": "small-boat fishing", "hi": "छोटी नाव से मछली पकड़ना", "ml": "ചെറുവള്ള മത്സ്യബന്ധനം", "ta": "சிறு படகு மீன்பிடி"},
    "act.fishing_mechanised": {"en": "mechanised fishing", "hi": "मशीनी नाव से मछली पकड़ना", "ml": "യന്ത്രവത്കൃത മത്സ്യബന്ധനം", "ta": "இயந்திர மீன்பிடி"},
    "act.swimming": {"en": "swimming", "hi": "तैराकी", "ml": "നീന്തൽ", "ta": "நீச்சல்"},
    "act.generic": {"en": "going to sea", "hi": "समुद्र में जाना", "ml": "കടലിൽ പോകൽ", "ta": "கடலுக்குச் செல்வது"},
    "act.cargo_transit": {"en": "vessel transit", "hi": "जहाज़ की यात्रा", "ml": "കപ്പൽ യാത്ര", "ta": "கப்பல் பயணம்"},
    "act.tourism": {"en": "a boat trip", "hi": "नाव की सैर", "ml": "ബോട്ട് യാത്ര", "ta": "படகுப் பயணம்"},
    # ---- follow-ups -------------------------------------------------------
    "followup.time": {"en": "What about 5 PM?", "hi": "शाम 5 बजे का क्या?", "ml": "വൈകുന്നേരം 5 മണിക്ക്?", "ta": "மாலை 5 மணிக்கு?"},
    "followup.pfz": {"en": "Where is the nearest fishing zone?", "hi": "निकटतम मछली क्षेत्र कहाँ है?", "ml": "അടുത്ത മത്സ്യബന്ധന മേഖല എവിടെ?", "ta": "அருகிலுள்ள மீன்பிடி மண்டலம் எங்கே?"},
    "followup.warnings": {"en": "Are there any warnings?", "hi": "क्या कोई चेतावनी है?", "ml": "എന്തെങ്കിലും മുന്നറിയിപ്പുണ്ടോ?", "ta": "ஏதேனும் எச்சரிக்கை உள்ளதா?"},
    "followup.avoid": {"en": "What areas should I avoid?", "hi": "मुझे किन क्षेत्रों से बचना चाहिए?", "ml": "ഏതൊക്കെ പ്രദേശങ്ങൾ ഒഴിവാക്കണം?", "ta": "எந்தப் பகுதிகளைத் தவிர்க்க வேண்டும்?"},
}


def t(key: str, language: Language | str, **kwargs) -> str:
    lang = language.value if isinstance(language, Language) else str(language)
    entry = CATALOG.get(key)
    if entry is None:
        return key
    template = entry.get(lang) or entry.get(FALLBACK.value) or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def has_language(language: Language | str) -> bool:
    lang = language.value if isinstance(language, Language) else str(language)
    return any(lang in entry for entry in CATALOG.values())


def supported_languages() -> list[str]:
    langs: set[str] = set()
    for entry in CATALOG.values():
        langs.update(entry.keys())
    return sorted(langs)

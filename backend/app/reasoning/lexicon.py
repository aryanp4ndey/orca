"""Multilingual keyword lexicon.

ORCA's internal representation is language-independent: a query in Malayalam and
its English translation must produce byte-identical ``QueryContext`` fields.
That is only possible if the *lexicon* is multilingual and the *logic* is not,
so all language-specific strings live in this one file and nothing downstream
ever branches on language again.

Coverage today: English, Hindi (Devanagari and romanised), Malayalam, Tamil.
Adding Telugu or Bengali is adding rows here - no code changes.
"""

from __future__ import annotations

from app.schemas.common import Activity, Intent, VesselClass

# --- script ranges used for language detection -----------------------------
SCRIPT_RANGES: list[tuple[str, int, int]] = [
    ("hi", 0x0900, 0x097F),   # Devanagari
    ("bn", 0x0980, 0x09FF),   # Bengali
    ("gu", 0x0A80, 0x0AFF),
    ("or", 0x0B00, 0x0B7F),
    ("ta", 0x0B80, 0x0BFF),
    ("te", 0x0C00, 0x0C7F),
    ("ml", 0x0D00, 0x0D7F),
]

# Romanised-Hindi markers. Presence of several of these in Latin script means
# the user is typing Hinglish, which is how most coastal users actually type.
ROMAN_HI_MARKERS = {
    "hai", "hai", "kya", "kal", "aaj", "subah", "shaam", "raat", "samundar",
    "samudra", "jaana", "jana", "safe", "mausam", "hawa", "lehar", "machli",
    "machhli", "nav", "naav", "kitna", "kaisa", "kaha", "kahan", "batao",
    "chahiye", "parso", "baje", "dopahar", "sagar", "tufan", "toofan",
}

# --- intent keywords -------------------------------------------------------
# weight, term.  Higher weight = more decisive.
INTENT_TERMS: dict[Intent, list[tuple[float, str]]] = {
    Intent.MARINE_SAFETY: [
        (3.0, "safe"), (3.0, "safety"), (2.5, "risky"), (2.5, "dangerous"),
        (2.0, "should i go"), (2.0, "can i go"), (2.0, "ok to go"),
        (3.0, "सुरक्षित"), (2.5, "खतरा"), (2.0, "जाना चाहिए"),
        (3.0, "surakshit"), (2.0, "khatra"), (2.0, "jaana safe"),
        (3.0, "സുരക്ഷിത"), (2.5, "അപകട"), (3.0, "பாதுகாப்ப"), (2.5, "ஆபத்த"),
        (1.5, "venture"), (1.5, "go out to sea"), (1.5, "put out to sea"),
    ],
    Intent.SEA_CONDITION: [
        (2.5, "sea condition"), (2.5, "sea state"), (2.0, "how is the sea"),
        (2.0, "wave"), (1.5, "swell"), (1.5, "current"), (2.0, "समुद्र की स्थिति"),
        (1.5, "लहर"), (1.5, "lehar"), (2.0, "samundar kaisa"),
        (2.0, "കടൽ"), (1.5, "തിരമാല"), (2.0, "கடல்"), (1.5, "அலை"),
        (1.5, "sea status"), (1.5, "sea like"),
    ],
    Intent.WEATHER_INFO: [
        (2.5, "weather"), (2.0, "forecast"), (1.5, "wind"), (1.5, "rain"),
        (1.5, "temperature"), (2.5, "मौसम"), (2.5, "mausam"), (1.5, "hawa"),
        (1.5, "बारिश"), (2.5, "കാലാവസ്ഥ"), (2.5, "வானிலை"), (1.5, "காற்று"),
    ],
    Intent.PFZ_LOOKUP: [
        (4.0, "pfz"), (4.0, "potential fishing zone"), (3.0, "fishing zone"),
        (2.5, "where to fish"), (2.5, "best place to fish"), (2.0, "fish today"),
        (3.0, "मछली पकड़ने का क्षेत्र"), (2.5, "machli kahan"),
        (3.0, "മത്സ്യബന്ധന മേഖല"), (3.0, "மீன்பிடி மண்டலம்"),
        (2.0, "good catch"), (2.0, "shoal"),
    ],
    Intent.HAZARD_CHECK: [
        (3.5, "cyclone"), (3.0, "lightning"), (3.0, "storm"), (3.0, "warning"),
        (2.5, "alert"), (2.5, "hazard"), (3.0, "thunderstorm"), (2.0, "tsunami"),
        (3.5, "चक्रवात"), (3.0, "तूफान"), (3.0, "toofan"), (3.0, "tufan"),
        (2.5, "चेतावनी"), (3.5, "ചുഴലിക്കാറ്റ്"), (3.0, "മുന്നറിയിപ്പ്"),
        (3.5, "புயல்"), (3.0, "எச்சரிக்கை"), (2.5, "kallakkadal"),
    ],
    Intent.AVOID_AREAS: [
        (3.5, "avoid"), (3.0, "areas to avoid"), (2.5, "restricted"),
        (2.5, "not allowed"), (2.5, "keep away"), (2.0, "no go"),
        (3.0, "बचना"), (2.5, "प्रतिबंधित"), (3.0, "ഒഴിവാക്ക"), (3.0, "தவிர்க்க"),
    ],
    Intent.ROUTE_RISK: [
        (4.0, "route"), (3.0, "safest way"), (2.5, "passage"), (2.5, "sail from"),
        (2.5, "navigate"), (2.0, "journey"), (3.0, "मार्ग"), (3.0, "रास्ता"),
        (3.0, "raasta"), (3.0, "പാത"), (3.0, "வழி"),
    ],
    Intent.ANALYTICAL: [
        (3.5, "why"), (3.0, "explain"), (2.5, "reason"), (2.5, "compare"),
        (2.0, "lower"), (2.0, "higher"), (3.0, "क्यों"), (3.0, "kyon"), (3.0, "kyun"),
        (3.5, "എന്തുകൊണ്ട്"), (3.5, "ஏன்"),
    ],
    Intent.LOCATION_INFO: [
        (2.5, "how far"), (2.5, "distance"), (2.0, "where am i"),
        (2.0, "कितनी दूर"), (2.0, "kitni door"), (2.5, "എത്ര ദൂരം"), (2.5, "எவ்வளவு தூரம்"),
    ],
    Intent.SMALL_TALK: [
        (2.0, "hello"), (2.0, "hi there"), (2.0, "namaste"), (2.0, "नमस्ते"),
        (2.0, "thanks"), (2.0, "thank you"), (2.0, "who are you"),
        (2.0, "what can you do"),
    ],
}

ACTIVITY_TERMS: dict[Activity, list[str]] = {
    Activity.FISHING_SMALL_BOAT: [
        "fishing", "fisherman", "fishermen", "fish", "catch", "net", "nets",
        "मछली", "machli", "machhli", "मछुआरा", "മത്സ്യബന്ധനം", "മീൻ", "மீன்பிடி", "மீன்",
        "country craft", "canoe", "vallam",
    ],
    Activity.FISHING_MECHANISED: ["trawler", "trawling", "mechanised boat", "mechanized boat", "purse seine"],
    Activity.SWIMMING: ["swim", "swimming", "bathe", "bathing", "तैरना", "നീന്ത", "நீச்சல்"],
    Activity.DIVING: ["dive", "diving", "scuba", "snorkel"],
    Activity.CARGO_TRANSIT: ["cargo", "shipping", "vessel transit", "container", "tanker", "barge"],
    Activity.PATROL: ["patrol", "coast guard", "coastguard", "rescue", "sar mission"],
    Activity.TOURISM: ["tourist", "tourism", "boat ride", "houseboat", "cruise", "ferry"],
    Activity.RESEARCH: ["survey", "sampling", "research cruise", "ctd", "buoy deployment"],
}

VESSEL_TERMS: dict[VesselClass, list[str]] = {
    VesselClass.CANOE: ["canoe", "catamaran", "country craft", "vallam", "non-motorised", "kattumaram"],
    VesselClass.SMALL_MOTORISED: ["small boat", "outboard", "obm", "fibre boat", "fiberglass", "ibm", "छोटी नाव", "chhoti naav"],
    VesselClass.MECHANISED: ["trawler", "mechanised", "mechanized", "purse seiner", "gillnetter"],
    VesselClass.LARGE: ["ship", "tanker", "container vessel", "cargo ship", "bulk carrier"],
}

# --- time vocabulary -------------------------------------------------------
DAY_OFFSETS: list[tuple[str, int]] = [
    ("day after tomorrow", 2), ("parso", 2), ("परसों", 2),
    ("tomorrow", 1), ("kal", 1), ("कल", 1), ("നാളെ", 1), ("நாளை", 1),
    ("tonight", 0), ("today", 0), ("aaj", 0), ("आज", 0), ("ഇന്ന്", 1 - 1), ("இன்று", 0),
    ("now", 0), ("abhi", 0), ("अभी", 0), ("ഇപ്പോൾ", 0), ("இப்போது", 0),
]

PART_OF_DAY: list[tuple[str, int]] = [
    ("early morning", 5), ("morning", 7), ("subah", 7), ("सुबह", 7),
    ("രാവിലെ", 7), ("காலை", 7), ("dawn", 5), ("sunrise", 6),
    ("noon", 12), ("midday", 12), ("dopahar", 13), ("दोपहर", 13),
    ("ഉച്ച", 13), ("மதியம்", 13),
    ("afternoon", 15),
    ("evening", 18), ("shaam", 18), ("शाम", 18), ("സന്ധ്യ", 18), ("വൈകുന്നേരം", 18),
    ("மாலை", 18), ("sunset", 18),
    ("night", 21), ("tonight", 21), ("raat", 21), ("रात", 21),
    ("രാത്രി", 21), ("இரவு", 21), ("midnight", 0),
]

CLOCK_SUFFIXES = ["baje", "बजे", "மணி", "മണി", "o'clock", "oclock", "hrs", "hours"]

RANGE_MARKERS = [("between", "and"), ("from", "to"), ("se", "tak"), ("से", "तक")]

NOW_TERMS = ["now", "right now", "currently", "at the moment", "abhi", "अभी",
             "ഇപ്പോൾ", "இப்போது", "current"]

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "ml": "Malayalam",
                  "ta": "Tamil", "bn": "Bengali", "te": "Telugu",
                  "gu": "Gujarati", "or": "Odia", "mr": "Marathi"}

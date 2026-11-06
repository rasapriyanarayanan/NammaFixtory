"""Complaint text processing: language ID, category classification (Tamil + English),
severity/safety cues, and text similarity.

Baseline = transparent keyword rules (no model download needed). A Transformer /
Sentence-Transformer upgrade path is documented in docs/MODEL_EVALUATION.md.
"""
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Tamil-script keywords + common Tanglish transliterations + English
KEYWORDS = {
    "pothole": ["pothole", "potholes", "pit in road", "hole in road", "பள்ளம்", "குழி", "pallam", "kuzhi", "gaddha"],
    "road_crack": ["crack", "cracks", "cracked", "விரிசல்", "virisal"],
    "road_damage": ["damaged road", "broken road", "road damage", "road is bad", "சாலை சேதம்", "சேதமடைந்த சாலை", "road kedu"],
    "blocked_drain": ["drain", "drainage", "sewage", "sewer", "gutter", "blocked", "overflow", "கழிவுநீர்", "கால்வாய்", "வடிகால்", "அடைப்பு", "kaalvai", "vadikaal", "adaippu"],
    "waterlogging": ["waterlog", "water logging", "water stagnation", "stagnant", "flood", "water stands", "waterlogging", "water-logging", "waterlogged", "தண்ணீர் தேங்கி", "நீர் தேக்கம்", "தேங்கிய", "தேங்கி", "மழை நீர்", "thanneer thengi"],
    "water_leakage": ["leak", "leaks", "leaking", "leakage", "pipe burst", "burst pipe", "pipeline", "கசிவு", "குழாய் உடைந்து", "kasivu"],
    "garbage": ["garbage", "trash", "waste", "dump", "litter", "rubbish", "bin overflow", "குப்பை", "kuppai"],
    "streetlight": ["streetlight", "street light", "lamp post", "light not working", "தெருவிளக்கு", "விளக்கு எரியவில்லை", "theruvilakku"],
}

SAFETY_CUES = [
    "accident", "fell", "fall", "injur", "danger", "dangerous", "school", "hospital", "children",
    "child", "bike", "two-wheeler", "night", "dark", "open manhole", "manhole", "deep", "விபத்து", "ஆபத்து",
    "பள்ளி", "மருத்துவமனை", "குழந்தை", "vibathu", "aabathu",
]

LOCATION_PAT = re.compile(
    r"(?:near|opposite|beside|behind|at|on|in|அருகில்|எதிரில்)\s+([A-Za-z0-9஀-௿ .'-]{3,40})",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    if not text:
        return "unknown"
    tamil = sum(1 for ch in text if "஀" <= ch <= "௿")
    letters = sum(1 for ch in text if ch.isalpha())
    if letters == 0:
        return "unknown"
    ratio = tamil / letters
    if ratio > 0.5:
        return "ta"
    if ratio > 0.1:
        return "ta-en"
    return "en"


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _has(t: str, w: str) -> bool:
    """Latin keywords match whole words (plus s/es/ed/ing), so 'wasted' is not 'waste'.
    Tamil keywords match as substrings because Tamil words take many suffixes."""
    w = w.lower()
    if w.isascii():
        return re.search(r"\b" + re.escape(w) + r"(?:s|es|ing|ed)?\b", t) is not None
    return w in t


def classify_text(text: str) -> dict:
    t = normalise(text)
    if not t:
        return {"category": None, "confidence": 0.0, "matched": []}
    hits = {}
    for cat, words in KEYWORDS.items():
        m = [w for w in words if _has(t, w)]
        if m:
            hits[cat] = m
    if not hits:
        return {"category": None, "confidence": 0.0, "matched": []}
    best = max(hits, key=lambda c: (len(hits[c]), max(len(w) for w in hits[c])))
    conf = min(0.9, 0.5 + 0.15 * len(hits[best]))
    return {"category": best, "confidence": round(conf, 2), "matched": hits[best]}


def safety_cues(text: str) -> list:
    t = normalise(text)
    return sorted({c for c in SAFETY_CUES if c in t})


def extract_location_hint(text: str):
    m = LOCATION_PAT.search(text or "")
    return m.group(1).strip() if m else None


def structure_complaint(text: str, location_text: str = "") -> dict:
    cls = classify_text(text)
    return {
        "language": detect_language(text),
        "category": cls["category"],
        "category_confidence": cls["confidence"],
        "matched_terms": cls["matched"],
        "location_hint": extract_location_hint(text) or (location_text or None),
        "safety_cues": safety_cues(text),
    }


def text_similarity(a: str, b: str) -> float:
    """Character n-gram TF-IDF cosine similarity (works across Tamil/English spelling variants)."""
    a, b = normalise(a), normalise(b)
    if not a or not b:
        return 0.0
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit([a, b])
        m = vec.transform([a, b])
        return float(cosine_similarity(m[0], m[1])[0][0])
    except ValueError:
        return 0.0

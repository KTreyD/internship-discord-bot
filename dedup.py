"""Cross-source duplicate detection.

Pure functions, no I/O. Two layers:

1. `fingerprint()` - an exact, deterministic normalized-key match used
   against the DB (one indexed lookup per batch, see database.find_existing).
2. `dedupe_batch()` - a stdlib, in-batch-only subset-of-tokens pass that
   catches near-duplicates within a single fetch (e.g. the same posting
   worded slightly differently across sources) before they ever reach the
   DB. This is NOT run against DB history - only exact fingerprint match is.

Exact-key matching (no rapidfuzz) is a deliberate choice: the blocking key
needed to make DB-side matching tractable *is* the normalized company key,
and the actual cross-source variance (punctuation, req IDs, year/season
suffixes, word order) is erased deterministically by normalize_title below.
A similarity threshold loose enough to catch typos is also loose enough to
merge "Mechanical Engineer Intern" with "Electrical Engineer Intern".
"""
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_LEGAL_SUFFIXES = (
    "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "gmbh", "ag", "sa", "nv", "holdings", "group", "technologies",
    "technology", "labs",
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_PAREN_RE = re.compile(r"[()]")
_BRACKET_RE = re.compile(r"[\[\]]")
_REQ_ID_RE = re.compile(r"(?<!\w)(?:req|job|jr|r)?[-#_]?\d{4,}(?!\w)")
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_SEASON_RE = re.compile(r"\b(summer|fall|autumn|winter|spring)\b")
_INTERNSHIP_RE = re.compile(r"\b(internship|intern)\b")
_COOP_RE = re.compile(r"\b(co-op|coop|co op)\b")
_AMP_RE = re.compile(r"&")
_SPLIT_RE = re.compile(r"[^a-z0-9]+")

_STOPWORDS = {
    "the", "a", "an", "of", "and", "for", "in", "at", "to", "on", "with",
    "our", "us", "usa", "united", "states", "remote", "hybrid", "onsite",
    "student", "students", "paid", "opportunity", "program", "position",
    "role", "hiring", "now", "full", "time", "parttime",
}


def _fold_ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def normalize_company(company: str) -> str:
    text = _fold_ascii(company or "").lower().strip()
    if text.startswith("the "):
        text = text[4:]

    # Repeatedly strip trailing legal suffixes (e.g. "Foo Labs, Inc." has two).
    changed = True
    while changed:
        changed = False
        stripped = _NON_ALNUM_RE.sub(" ", text).strip()
        for suffix in _LEGAL_SUFFIXES:
            if stripped == suffix:
                continue
            if stripped.endswith(" " + suffix):
                stripped = stripped[: -(len(suffix) + 1)].strip()
                text = stripped
                changed = True
                break

    text = _NON_ALNUM_RE.sub("", text)
    return text


def normalize_title(title: str) -> str:
    text = _fold_ascii(title or "").lower()

    # Strip only the bracket characters themselves - keep the contents as
    # tokens. "(Substation)" and "(Distribution)" are different roles, not
    # noise; "(Summer 2027)" still normalizes away because the season/year
    # rules below run over the now-exposed text.
    text = _PAREN_RE.sub(" ", text)
    text = _BRACKET_RE.sub(" ", text)
    text = _REQ_ID_RE.sub(" ", text)
    text = _YEAR_RE.sub(" ", text)
    text = _SEASON_RE.sub(" ", text)

    text = _INTERNSHIP_RE.sub("intern", text)
    text = _COOP_RE.sub("intern", text)
    text = _AMP_RE.sub("and", text)

    tokens = [t for t in _SPLIT_RE.split(text) if t and t not in _STOPWORDS]

    # Dedupe while preserving nothing in particular, then sort - word order
    # is exactly the cross-source divergence this needs to erase.
    unique_sorted = sorted(set(tokens))
    return "-".join(unique_sorted)


_VOLATILE_QUERY_PREFIXES = ("utm_",)
_VOLATILE_QUERY_KEYS = {"se"}


def normalize_url(url: str) -> str:
    """Normalizes a job posting URL for dedup purposes.

    Lowercases scheme+host, strips a leading "www.", drops a trailing slash
    from the path, removes volatile query params (session tokens, utm_*)
    while keeping meaningful ones (v, gh_jid, lever-origin, ...), sorts the
    surviving params, and drops the fragment. Conservative: unknown params
    are kept. Idempotent. Never raises - returns the input unchanged if it
    can't be parsed (including empty/None input).
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        netloc = (parts.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parts.path or ""
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]

        kept_pairs = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _VOLATILE_QUERY_KEYS
            and not k.lower().startswith(_VOLATILE_QUERY_PREFIXES)
        ]
        kept_pairs.sort()
        query = urlencode(kept_pairs)

        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return url


# Full US state names (lowercase) -> 2-letter abbreviation, so "Dallas,
# Texas" and "Dallas, TX" normalize to the same location key.
_US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct",
    "delaware": "de", "florida": "fl", "georgia": "ga", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me",
    "maryland": "md", "massachusetts": "ma", "michigan": "mi",
    "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm",
    "new york": "ny", "north carolina": "nc", "north dakota": "nd",
    "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd",
    "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy",
    "district of columbia": "dc",
}

_LOCATION_PUNCT_RE = re.compile(r"[^a-z0-9,\s]+")
_LOCATION_SPACE_RE = re.compile(r"\s+")


def normalize_location(location: str) -> str:
    """Coarse location key: lowercase, ASCII-fold, strip punctuation, expand
    full US state names to their 2-letter abbreviation. Any "remote" mention
    collapses to "remote". Empty/None input returns ""."""
    if not location:
        return ""

    text = _fold_ascii(location).lower()
    if "remote" in text:
        return "remote"

    text = _LOCATION_PUNCT_RE.sub(" ", text)
    parts = [p.strip() for p in text.split(",")]
    parts = [_LOCATION_SPACE_RE.sub(" ", p).strip() for p in parts if p.strip()]
    if not parts:
        return ""

    if parts[-1] in _US_STATES:
        parts[-1] = _US_STATES[parts[-1]]

    tokens = [p.replace(" ", "-") for p in parts]
    return "-".join(tokens)


def fingerprint(company: str, title: str, location: str = "") -> str:
    return f"{normalize_company(company)}|{normalize_title(title)}|{normalize_location(location)}"


_SOURCE_PRIORITY = {"ats": 0, "github": 1, "adzuna": 2}


def _source_priority(source: str) -> int:
    source = (source or "").lower()
    if source.startswith("greenhouse") or source.startswith("lever"):
        return _SOURCE_PRIORITY["ats"]
    if "github" in source or "/" in source:
        # GitHub source names are repo slugs like "org/repo".
        return _SOURCE_PRIORITY["github"]
    if source.startswith("adzuna"):
        return _SOURCE_PRIORITY["adzuna"]
    return _SOURCE_PRIORITY["github"]


def _survivor(a, b):
    """Picks the better of two duplicate Job objects: longest description,
    tie-broken by source priority ATS > GitHub > Adzuna."""
    len_a, len_b = len(a.description or ""), len(b.description or "")
    if len_a != len_b:
        return a if len_a > len_b else b
    return a if _source_priority(a.source) <= _source_priority(b.source) else b


def dedupe_batch(jobs):
    """In-batch-only near-duplicate collapse.

    Groups by normalized company key, then within each group treats title A
    as a duplicate of title B if tokens(A) is a subset of tokens(B) (or vice
    versa) and the smaller token set has >= 3 tokens. O(k^2) within one
    company's postings in a single batch.

    Returns (kept_jobs, dropped_count).
    """
    groups: dict[str, list] = {}
    for job in jobs:
        key = normalize_company(job.company)
        groups.setdefault(key, []).append(job)

    kept = []
    dropped = 0

    for company_key, group_jobs in groups.items():
        survivors = []
        survivor_tokens = []

        for job in group_jobs:
            tokens = set(normalize_title(job.title).split("-"))
            tokens.discard("")

            merged = False
            for i, existing_tokens in enumerate(survivor_tokens):
                smaller, larger = (
                    (tokens, existing_tokens)
                    if len(tokens) <= len(existing_tokens)
                    else (existing_tokens, tokens)
                )
                if len(smaller) >= 3 and smaller.issubset(larger):
                    survivors[i] = _survivor(survivors[i], job)
                    survivor_tokens[i] = set(normalize_title(survivors[i].title).split("-"))
                    survivor_tokens[i].discard("")
                    merged = True
                    dropped += 1
                    break

            if not merged:
                survivors.append(job)
                survivor_tokens.append(tokens)

        kept.extend(survivors)

    return kept, dropped

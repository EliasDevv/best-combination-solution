"""Team-name normalization.

User input ("Bayern München", "bayern munchen", "FC Bayern München") must map
to a single canonical key so that autocomplete selections and CSV team names
agree. The normalized form is the key of ``BitIndex.team_mask``.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

# Corporate/legal suffixes and prefixes that carry no identity: "FC Bayern"
# and "Bayern" are the same club. Only tokens that are unambiguous noise are
# listed; city names or "United"/"City" style tokens are identity and stay.
_NOISE_TOKENS = frozenset({"fc", "cf", "afc", "cfc", "ac", "sv", "tsv", "vfb", "vfl"})

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _strip_diacritics(text: str) -> str:
    """Remove combining marks: ``München`` -> ``Munchen``, ``Real Sociedad`` unchanged."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def search_fold(text: str) -> str:
    """Fold a display name or query for autocomplete matching.

    Only strips diacritics and casefolds. Unlike ``normalize_team_name`` it
    keeps punctuation and noise tokens: autocomplete matches what the user
    sees ("FC St. Pauli"), not the canonical mask key.
    """
    return _strip_diacritics(text).casefold()


def normalize_team_name(name: str) -> str:
    """Return a canonical lookup key for a team name.

    Steps, in order:

    1. Strip diacritics (``ü`` -> ``u``).
    2. Casefold (aggressive lowercase, handles ``ß`` -> ``ss``).
    3. Replace punctuation with spaces (``1. FC Köln`` -> ``1 FC Koln``).
    4. Collapse runs of whitespace.
    5. Drop noise tokens like ``fc``/``cf`` — unless that would leave nothing,
       in which case the cleaned name is kept as-is (a club literally named
       "FC" must not normalize to the empty string).

    >>> normalize_team_name("FC Bayern München")
    'bayern munchen'
    >>> normalize_team_name("Los Angeles FC")
    'los angeles'
    """
    cleaned = _strip_diacritics(name).casefold()
    cleaned = _NON_WORD_RE.sub(" ", cleaned)
    tokens = _WHITESPACE_RE.split(cleaned.strip())
    tokens = [t for t in tokens if t]
    kept = [t for t in tokens if t not in _NOISE_TOKENS]
    return " ".join(kept if kept else tokens)


def _noise_signature(name: str) -> frozenset[str]:
    """The noise tokens present in a raw name (before they get dropped)."""
    cleaned = _strip_diacritics(name).casefold()
    cleaned = _NON_WORD_RE.sub(" ", cleaned)
    tokens = [t for t in _WHITESPACE_RE.split(cleaned.strip()) if t]
    return frozenset(t for t in tokens if t in _NOISE_TOKENS)


def find_suspicious_collisions(names: Iterable[str]) -> dict[str, list[str]]:
    """Normalized keys that may merge two *different* clubs into one mask.

    Raw names are grouped by their normalized key. A key is suspicious when
    at least two of its raw names carry different noise-token sets — e.g.
    "SV Werder" and "VfL Werder" both normalize to "werder" but could name
    distinct clubs. Pure spelling variants (case, diacritics, punctuation)
    share a signature and are not reported. Returns key -> sorted raw names.
    """
    by_key: dict[str, dict[str, frozenset[str]]] = defaultdict(dict)
    for name in names:
        by_key[normalize_team_name(name)].setdefault(name, _noise_signature(name))
    return {
        key: sorted(raw)
        for key, raw in by_key.items()
        if len(raw) > 1 and len(set(raw.values())) > 1
    }

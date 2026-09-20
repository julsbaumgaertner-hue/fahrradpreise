"""
Fuzzy-Pruefung der Treffertitel gegen die match_required/match_boost-Tokens
aus config/models.yaml. Siehe dortige Kommentare fuer die Begruendung.
"""

from __future__ import annotations

from rapidfuzz import fuzz

REQUIRED_THRESHOLD = 75  # ab hier gilt ein Pflicht-Token als "im Titel enthalten"
BOOST_THRESHOLD = 75
BASE_SCORE = 50
BOOST_PER_HIT = 10


def score_title(title: str, match_required: list[str], match_boost: list[str]) -> float | None:
    """None, wenn nicht ALLE match_required-Tokens (fuzzy) im Titel vorkommen.
    Sonst ein Score 0-100: BASE_SCORE + BOOST_PER_HIT je getroffenem
    Boost-Token (gedeckelt bei 100)."""
    title_l = title.lower()

    for token in match_required:
        if fuzz.partial_ratio(token.lower(), title_l) < REQUIRED_THRESHOLD:
            return None

    boost_hits = sum(
        1 for token in match_boost
        if fuzz.partial_ratio(token.lower(), title_l) >= BOOST_THRESHOLD
    )
    return min(100.0, BASE_SCORE + boost_hits * BOOST_PER_HIT)

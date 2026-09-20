"""
Fuzzy-Pruefung der Treffertitel gegen die match_required/match_boost-Tokens
aus config/models.yaml. Siehe dortige Kommentare fuer die Begruendung.

Ausserdem: guess_color() - gemeinsame Best-Effort-Farberkennung aus dem
Freitext-Titel fuer alle Quellen, die selbst kein strukturiertes
Farbfeld liefern (das ist fast jede - siehe Kommentar dort unten). Nur
jobrad-loop.com hatte bei der Pruefung (20.09.2026) ein echtes
attributes.color-Feld; alle anderen Quellen bekommen das hier als
Rate-Heuristik. Faerbereien bei E-Bikes nutzen oft zusammengesetzte
Markennamen wie "deepcobalt'n'black" oder "swampgrey'n'purplereflex" -
die Muster unten matchen auf den enthaltenen Grundfarben-Wortstamm statt
exakte Markennamen zu kennen, und liefern bewusst nur EINE (die erste
gefundene) Farbe pro Titel statt aller Nennungen.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

# Reihenfolge = Prioritaet bei mehreren Treffern im selben Titel.
_COLOR_PATTERNS: list[tuple[str, re.Pattern]] = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in [
        ("Schwarz", r"schwarz|black"),
        ("Weiß", r"wei(?:s|ß)s?|white"),
        ("Carbon/Raw", r"\bcarbon\b|\braw\b|matte\s*raw"),
        ("Grau", r"grau|gr[ea]y|anthrazit|titan(?:ium)?"),
        ("Blau", r"blau|blue|cobalt|navy|petrol"),
        ("Rot", r"\brot\b|\bred\b"),
        ("Grün", r"gr[uü]n|green|\boliv\w*|mint"),
        ("Gelb", r"gelb|yellow"),
        ("Orange", r"orange"),
        ("Lila/Violett", r"lila|violett?|purple"),
        ("Pink", r"pink|magenta"),
        ("Gold", r"gold"),
        ("Silber", r"silber|silver"),
        ("Braun", r"braun|brown|bronze|copper|kupfer"),
        ("Beige", r"beige|\bsand\b|\breed\w*"),
    ]
]


def guess_color(title: str) -> str | None:
    """Best-effort Farberkennung aus dem Titel - siehe Moduldoc oben.
    None, wenn kein bekanntes Farbwort im Titel vorkommt (haeufig, kein
    Fehler)."""
    for label, pattern in _COLOR_PATTERNS:
        if pattern.search(title):
            return label
    return None

# Erkennt Rahmen-only-Angebote (keine kompletten Raeder) an eindeutigen
# Signalwoertern. Bewusst eng gehalten: eine breite Zubehoer-Keywordliste
# (Schloss, Helm, Licht, ...) wurde live gegen die echten 933 Treffer
# getestet und produzierte Fehltreffer - z.B. "Focus JAM SL 8.7 ... +
# Schloss" ist ein kompletter Bike-Verkauf, bei dem nur ein Schloss als
# Zugabe erwaehnt wird, kein Zubehoer-Einzelangebot. "\brahmen\b" matcht
# wegen der Wortgrenze NICHT auf zusammengesetzte Woerter wie
# "Rahmengroesse" oder "Rahmennummer"/"Carbonrahmen" (kein Leerzeichen
# davor/danach im Deutschen), nur auf das eigenstaendige Wort "Rahmen".
#
# Zweiter Fall (per Screenshot vom Nutzer gefunden: "Scott LUMEN Eride
# 900SL Carbon Rahmen Größe S" wurde NICHT erfasst): Verkaeufer schreiben
# das eigenstaendige Wort "Rahmen" oft mitten im Titel direkt neben der
# Rahmengroesse ("XL Rahmen", "Rahmen L", "Rahmen Größe S") - live gegen
# die echten 924 damaligen Treffer geprueft: 6 weitere Faelle gefunden,
# alle echte Rahmen-only-Angebote, keine neuen Fehltreffer gegen bekannte
# komplette Bike-Titel (inkl. "Carbonrahmen"-Erwaehnungen, "Gr. M (...)"-
# Groessenangaben ohne "Rahmen" in der Naehe).
_GROESSEN_TOKEN = r"(?:XXS|XS|S|M|L|XL|XXL)"
_RAHMEN_ONLY_MUSTER = re.compile(
    r"\bframeset\b|\brahmenkit\b|\brahmenset\b|\bhauptrahmen\b"
    r"|^rahmen\b|\bnur\s+(?:der\s+)?rahmen\b|\brahmen\s+only\b"
    rf"|\b{_GROESSEN_TOKEN}\b[\s\W]{{0,4}}\brahmen\b"
    rf"|\brahmen\b[\s\W]{{0,15}}(?:gr\.?|größe|groesse|grosse)?[\s\W]{{0,4}}\b{_GROESSEN_TOKEN}\b",
    re.IGNORECASE,
)


def ist_rahmen_only(title: str) -> bool:
    """True, wenn der Titel eindeutig ein Rahmen-only-Angebot ist (kein
    komplettes Rad) - siehe Kommentar oben zur Begruendung der engen
    Muster."""
    return bool(_RAHMEN_ONLY_MUSTER.search(title))


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

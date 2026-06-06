"""
Static FIFA men's world ranking snapshot used by the WC2026 prediction layer.

Phase 1 only: predictions for the FIFA World Cup 2026 are derived
deterministically from FIFA rankings. The ranks below are a snapshot of the
public FIFA/Coca-Cola Men's World Ranking ordering for nations that qualified
(or are realistically expected to qualify) for the WC2026 expanded 48-team
tournament. They are intended to be refreshed monthly by manual edit until a
proper international-results ML model lands in Phase 2.

Team-name keys MUST match the canonical names used in
`db/seed_wc2026.py::GROUPS` (which mirror `src/wc2026/pages/Groups.tsx
STATIC_GROUPS`). Lookups via `get_rank` are case-insensitive and tolerant of a
small number of common aliases (e.g. "South Korea" -> "Korea Republic").

Unknown teams fall back to `DEFAULT_RANK`, which sits at the lower end of the
distribution so they are treated as underdogs without producing zero
probabilities.
"""
from __future__ import annotations

from typing import Dict, Final, Optional


# Snapshot ordering (manually curated, FIFA-canonical names).
# Lower number = stronger team. Ranks need not be globally contiguous —
# only the relative ordering between WC2026 participants matters for Elo.
FIFA_RANKING: Final[Dict[str, int]] = {
    "Argentina": 1,
    "Spain": 2,
    "France": 3,
    "England": 4,
    "Brazil": 5,
    "Portugal": 6,
    "Netherlands": 7,
    "Belgium": 8,
    "Croatia": 9,
    "Germany": 10,
    "Italy": 11,
    "Colombia": 12,
    "Morocco": 13,
    "Uruguay": 14,
    "USA": 15,
    "Switzerland": 16,
    "Senegal": 17,
    "Mexico": 18,
    "Japan": 19,
    "Denmark": 20,
    "IR Iran": 21,
    "Korea Republic": 22,
    "Ecuador": 23,
    "Ukraine": 24,
    "Austria": 25,
    "Australia": 26,
    "Türkiye": 27,
    "Sweden": 28,
    "Wales": 29,
    "Hungary": 30,
    "Serbia": 31,
    "Poland": 32,
    "Canada": 33,
    "Egypt": 34,
    "Russia": 35,
    "Czechia": 36,
    "Romania": 37,
    "Greece": 38,
    "Algeria": 39,
    "Norway": 40,
    "Tunisia": 41,
    "Côte d'Ivoire": 42,
    "Scotland": 43,
    "Slovakia": 44,
    "Nigeria": 45,
    "Cameroon": 46,
    "Mali": 47,
    "Paraguay": 48,
    "Saudi Arabia": 49,
    "Peru": 50,
    "Slovenia": 51,
    "Republic of Ireland": 52,
    "Costa Rica": 53,
    "Iceland": 54,
    "Burkina Faso": 55,
    "Venezuela": 56,
    "Albania": 57,
    "Uzbekistan": 58,
    "Finland": 59,
    "South Africa": 60,
    "Iraq": 61,
    "Jamaica": 62,
    "Cabo Verde": 63,
    "Bolivia": 64,
    "Congo DR": 65,
    "Northern Ireland": 66,
    "Montenegro": 67,
    "Honduras": 68,
    "Panama": 69,
    "Bulgaria": 70,
    "Ghana": 71,
    "Belarus": 72,
    "Georgia": 73,
    "Bosnia and Herzegovina": 74,
    "United Arab Emirates": 75,
    "Curacao": 76,
    "Qatar": 77,
    "El Salvador": 78,
    "China PR": 79,
    "Israel": 80,
    "Jordan": 81,
    "Oman": 82,
    "Luxembourg": 83,
    "Bahrain": 84,
    "North Macedonia": 85,
    "Haiti": 86,
    "Syria": 87,
    "Kazakhstan": 88,
    "New Zealand": 89,
    "Vietnam": 90,
    "India": 91,
    "Armenia": 92,
    "Kosovo": 93,
    "Estonia": 94,
    "Cyprus": 95,
    "Trinidad and Tobago": 96,
    "Kyrgyzstan": 97,
    "Latvia": 98,
    "Faroe Islands": 99,
    "Lithuania": 100,
}


# Fallback rank used when a team is not in FIFA_RANKING. Slightly below the
# median so unknown sides do not receive an unrealistic advantage.
DEFAULT_RANK: Final[int] = 80


# Common aliases — frontend strings that don't match FIFA-canonical naming.
# Lookups are case-insensitive; keys here MUST be lowercased.
_ALIASES: Final[Dict[str, str]] = {
    "south korea": "Korea Republic",
    "korea south": "Korea Republic",
    "czech republic": "Czechia",
    "united states": "USA",
    "united states of america": "USA",
    "u.s.a.": "USA",
    "turkey": "Türkiye",
    "ivory coast": "Côte d'Ivoire",
    "cote d'ivoire": "Côte d'Ivoire",
    "cape verde": "Cabo Verde",
    "iran": "IR Iran",
    "dr congo": "Congo DR",
    "congo dr": "Congo DR",
    "democratic republic of the congo": "Congo DR",
    "bosnia": "Bosnia and Herzegovina",
    "curaçao": "Curacao",
}


def _canonical(name: str) -> str:
    """
    Resolve a free-form team name to its FIFA-canonical key.

    Falls back to the input (stripped) if no alias and no direct match exists.
    """
    if not name:
        return ""
    cleaned = name.strip()
    if cleaned in FIFA_RANKING:
        return cleaned

    lower = cleaned.lower()
    alias = _ALIASES.get(lower)
    if alias is not None:
        return alias

    # Case-insensitive match against canonical names.
    for canonical in FIFA_RANKING:
        if canonical.lower() == lower:
            return canonical

    return cleaned


def get_rank(team: str) -> int:
    """
    Return the FIFA rank for a team, or `DEFAULT_RANK` if unknown.

    Args:
        team: Team name (canonical FIFA name or supported alias).

    Returns:
        Integer rank. Lower is stronger.
    """
    canonical = _canonical(team)
    return FIFA_RANKING.get(canonical, DEFAULT_RANK)


def has_rank(team: str) -> bool:
    """
    True if the team has an explicit (non-fallback) entry in the ranking.
    """
    canonical = _canonical(team)
    return canonical in FIFA_RANKING


def canonical_name(team: str) -> Optional[str]:
    """
    Return the canonical FIFA name for a team, or None if not known.
    """
    canonical = _canonical(team)
    return canonical if canonical in FIFA_RANKING else None

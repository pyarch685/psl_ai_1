"""
FIFA-ranking-based prediction layer for WC2026 (Phase 1).

The PSL ML model in `core/prediction.py` is trained on PSL clubs only — it
has no Elo or form entries for national teams, so it would return roughly
uniform probabilities for WC2026 fixtures. Rather than block the launch on
training a proper international model, Phase 1 ships a deterministic
prediction derived from FIFA rankings:

1. Convert each team's FIFA rank into an Elo rating via a linear mapping:
       elo = 2100 - (rank - 1) * 6
   clamped to [1300, 2100].

2. Compute the standard Elo win expectancy on the Elo diff (no home
   advantage — WC2026 matches are at neutral venues).

3. Carve out a fixed draw probability from the closer side. The closer the
   two teams in Elo, the larger the draw share — matching empirical
   international-football draw rates (~22%).

Same response shape as `core.prediction.predict_softmax`:
    {"Home": float, "Draw": float, "Away": float}

All predictions tagged with `MODEL_VERSION` so a Phase 2 ML model can swap in
without breaking benchmark history.
"""
from __future__ import annotations

from typing import Dict, Final

from core.fifa_rankings import get_rank


MODEL_VERSION: Final[str] = "fifa_elo_v1"


# Elo derivation tuning (see module docstring).
_ELO_TOP: Final[float] = 2100.0
_ELO_FLOOR: Final[float] = 1300.0
_ELO_PER_RANK: Final[float] = 6.0


# Draw probability shaping. We start from a baseline draw share and reduce it
# as the Elo gap widens — large mismatches make draws less likely.
_DRAW_BASE: Final[float] = 0.30
_DRAW_FLOOR: Final[float] = 0.10
_DRAW_DECAY_PER_100_ELO: Final[float] = 0.04


def rank_to_elo(rank: int) -> float:
    """
    Map a FIFA rank (1 = best) to an Elo rating.

    Args:
        rank: Positive integer rank (1 is strongest).

    Returns:
        Elo rating clamped to [_ELO_FLOOR, _ELO_TOP].
    """
    if rank < 1:
        rank = 1
    elo = _ELO_TOP - (rank - 1) * _ELO_PER_RANK
    if elo < _ELO_FLOOR:
        return _ELO_FLOOR
    if elo > _ELO_TOP:
        return _ELO_TOP
    return elo


def _draw_share(elo_diff: float) -> float:
    """
    Compute the draw probability given the absolute Elo difference.

    Equal teams ≈ `_DRAW_BASE`; very lopsided matchups asymptote to `_DRAW_FLOOR`.
    """
    abs_diff = abs(elo_diff)
    share = _DRAW_BASE - (abs_diff / 100.0) * _DRAW_DECAY_PER_100_ELO
    if share < _DRAW_FLOOR:
        return _DRAW_FLOOR
    return share


def predict(home_team: str, away_team: str) -> Dict[str, float]:
    """
    Predict outcome probabilities for a WC2026 match.

    Args:
        home_team: Home team name (FIFA canonical or supported alias).
        away_team: Away team name (FIFA canonical or supported alias).

    Returns:
        Dict with keys "Home", "Draw", "Away" summing to 1.0.
    """
    home_elo = rank_to_elo(get_rank(home_team))
    away_elo = rank_to_elo(get_rank(away_team))

    # No home advantage — WC2026 group matches are at neutral venues.
    elo_diff = home_elo - away_elo

    # Standard Elo expected-win formula gives the home side's expectancy
    # against the away side, ignoring draws.
    home_expectancy = 1.0 / (1.0 + 10.0 ** (-elo_diff / 400.0))
    away_expectancy = 1.0 - home_expectancy

    draw = _draw_share(elo_diff)
    home = home_expectancy * (1.0 - draw)
    away = away_expectancy * (1.0 - draw)

    # Normalize to guard against any floating-point drift.
    total = home + draw + away
    return {
        "Home": home / total,
        "Draw": draw / total,
        "Away": away / total,
    }


def outcome_from_probs(probs: Dict[str, float]) -> str:
    """
    Pick the most likely outcome label ("Home", "Draw", "Away").
    """
    return max(probs.items(), key=lambda x: x[1])[0]


def group_winner_probability(group_teams: list[str]) -> Dict[str, float]:
    """
    Estimate group-winner probabilities by softmax over Elo.

    Args:
        group_teams: Iterable of team names in the group.

    Returns:
        Dict mapping team name -> winner probability (sums to 1.0). Returns
        an empty dict if `group_teams` is empty.
    """
    teams = list(group_teams)
    if not teams:
        return {}

    import math

    elos = {t: rank_to_elo(get_rank(t)) for t in teams}
    # Temperature controls how sharp the distribution is. 200 Elo ≈ one
    # standard deviation of strength under our linear mapping; using it as
    # the softmax denominator gives realistically-spread probabilities.
    temperature = 200.0
    max_elo = max(elos.values())
    exps = {t: math.exp((e - max_elo) / temperature) for t, e in elos.items()}
    z = sum(exps.values())
    return {t: v / z for t, v in exps.items()}

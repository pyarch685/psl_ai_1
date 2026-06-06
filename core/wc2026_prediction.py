"""
Prediction layer for WC2026.

This module is the single public entry point used by the API and scheduled
jobs. It picks between two underlying models at request time:

1. **Phase 2 — Davidson-Bradley-Terry** (`core.wc2026_model`):
   Fitted via `python3 -m core.wc2026_train` against the
   `wc2026_48_teams_h2h_summary_2006_2026.csv` dataset. Used by default
   whenever both teams have at least `MIN_MATCHES_FOR_BT` observed matches
   in the training data.

2. **Phase 1 — FIFA-Elo prior** (this module's `_fifa_elo_predict`):
   Maps each team's FIFA rank into an Elo rating and applies the
   standard expected-win formula plus a hand-tuned draw share. Used as a
   graceful fallback when the BT artifact is missing/corrupt OR either
   team is a cold-start in the H2H dataset (e.g. Curacao, which has zero
   matches against any other WC2026 nation in 2006-2026).

The public surface preserves the original Phase 1 contract:

    predict(home_team, away_team) -> {"Home": float, "Draw": float, "Away": float}
    outcome_from_probs(probs) -> "Home" | "Draw" | "Away"
    group_winner_probability(teams) -> {team: float}
    MODEL_VERSION: str

`MODEL_VERSION` reflects *whichever* underlying model was actually used —
when the BT artifact is loaded successfully it advertises the BT version,
otherwise the Phase 1 version. Predictions persisted to the DB by the
scheduler therefore carry the correct provenance.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Dict, Final, Optional

from core.fifa_rankings import _canonical, get_rank
from core.wc2026_model import (
    BTArtifact,
    MODEL_VERSION as BT_MODEL_VERSION,
    load_artifact as _load_bt_artifact,
    predict_probs as _bt_predict_probs,
)

logger = logging.getLogger(__name__)


# Phase 1 (fallback) constants -------------------------------------------------

_PHASE1_VERSION: Final[str] = "fifa_elo_v1"
_ELO_TOP: Final[float] = 2100.0
_ELO_FLOOR: Final[float] = 1300.0
_ELO_PER_RANK: Final[float] = 6.0
_DRAW_BASE: Final[float] = 0.30
_DRAW_FLOOR: Final[float] = 0.10
_DRAW_DECAY_PER_100_ELO: Final[float] = 0.04


# Artifact loading -------------------------------------------------------------

# Allow ops to override the artifact path via env var (e.g. mounting a fresh
# model into the Railway container without a code change). Defaults to the
# repo-relative path that `core.wc2026_train` writes to.
_DEFAULT_ARTIFACT_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "data" / "models" / "wc2026_bt.joblib"
)
ARTIFACT_PATH: Final[Path] = Path(
    os.getenv("WC2026_MODEL_PATH", str(_DEFAULT_ARTIFACT_PATH))
)


# Minimum observed matches a team needs in the H2H dataset before the BT
# strength is considered reliable. Cold-start teams (Curacao in our 2006-2026
# data — zero recorded matches against any other WC48 nation) get routed to
# the FIFA-Elo fallback instead of being silently pinned to "average team".
MIN_MATCHES_FOR_BT: Final[int] = int(os.getenv("WC2026_MIN_MATCHES_FOR_BT", "1"))


def _try_load_bt() -> Optional[BTArtifact]:
    """Load the BT artifact if available; return None on any failure.

    Failures are logged at WARNING so a missing artifact is visible at startup
    but never blocks the API from booting (Phase 1 is a complete fallback).
    """
    if not ARTIFACT_PATH.exists():
        logger.warning(
            "WC2026 BT artifact not found at %s — falling back to FIFA-Elo.",
            ARTIFACT_PATH,
        )
        return None
    try:
        artifact = _load_bt_artifact(ARTIFACT_PATH)
    except Exception as exc:
        logger.warning(
            "WC2026 BT artifact at %s failed to load (%s) — falling back to FIFA-Elo.",
            ARTIFACT_PATH,
            exc,
        )
        return None
    logger.info(
        "Loaded WC2026 BT artifact (%s): %d teams, %d matches, nu=%+.4f",
        artifact.model_version,
        len(artifact.teams),
        artifact.n_matches,
        artifact.draw_param,
    )
    return artifact


_BT_ARTIFACT: Optional[BTArtifact] = _try_load_bt()


def _model_in_use() -> str:
    """Return the version tag of whichever model is actually serving."""
    if _BT_ARTIFACT is None:
        return _PHASE1_VERSION
    return _BT_ARTIFACT.model_version


# Backwards-compatible constant — historical callers (e.g. prediction-store
# tagging) may read this at import. It reflects the *active* model.
MODEL_VERSION: str = _model_in_use()


# Phase 1 fallback -------------------------------------------------------------

def rank_to_elo(rank: int) -> float:
    """Map a FIFA rank (1 = best) to an Elo rating clamped to [floor, top]."""
    if rank < 1:
        rank = 1
    elo = _ELO_TOP - (rank - 1) * _ELO_PER_RANK
    if elo < _ELO_FLOOR:
        return _ELO_FLOOR
    if elo > _ELO_TOP:
        return _ELO_TOP
    return elo


def _draw_share(elo_diff: float) -> float:
    """Phase 1 draw share — starts at `_DRAW_BASE`, decays with Elo gap."""
    abs_diff = abs(elo_diff)
    share = _DRAW_BASE - (abs_diff / 100.0) * _DRAW_DECAY_PER_100_ELO
    if share < _DRAW_FLOOR:
        return _DRAW_FLOOR
    return share


def _fifa_elo_predict(home_team: str, away_team: str) -> Dict[str, float]:
    """Phase 1 prediction — pure FIFA-Elo derivation, no training data."""
    home_elo = rank_to_elo(get_rank(home_team))
    away_elo = rank_to_elo(get_rank(away_team))
    elo_diff = home_elo - away_elo

    home_expectancy = 1.0 / (1.0 + 10.0 ** (-elo_diff / 400.0))
    away_expectancy = 1.0 - home_expectancy

    draw = _draw_share(elo_diff)
    home = home_expectancy * (1.0 - draw)
    away = away_expectancy * (1.0 - draw)

    total = home + draw + away
    return {
        "Home": home / total,
        "Draw": draw / total,
        "Away": away / total,
    }


# Public API -------------------------------------------------------------------

def _has_enough_bt_evidence(team: str) -> bool:
    """True if the BT artifact has enough observed matches for `team`."""
    if _BT_ARTIFACT is None:
        return False
    canonical = _canonical(team) or team
    if canonical not in _BT_ARTIFACT.strengths:
        return False
    return _BT_ARTIFACT.n_matches_per_team.get(canonical, 0) >= MIN_MATCHES_FOR_BT


def predict(home_team: str, away_team: str) -> Dict[str, float]:
    """Predict outcome probabilities for a WC2026 match.

    Routes through the trained Davidson-BT model when both teams have at
    least `MIN_MATCHES_FOR_BT` observed matches; otherwise uses the FIFA-Elo
    fallback so cold-start nations still get a calibrated answer.

    Args:
        home_team: Home team name (FIFA-canonical or supported alias).
        away_team: Away team name (FIFA-canonical or supported alias).

    Returns:
        Dict with keys "Home", "Draw", "Away" summing to 1.0.
    """
    if _BT_ARTIFACT is not None and _has_enough_bt_evidence(home_team) and _has_enough_bt_evidence(away_team):
        canonical_home = _canonical(home_team) or home_team
        canonical_away = _canonical(away_team) or away_team
        return _bt_predict_probs(_BT_ARTIFACT, canonical_home, canonical_away)

    return _fifa_elo_predict(home_team, away_team)


def outcome_from_probs(probs: Dict[str, float]) -> str:
    """Pick the most likely outcome label ("Home", "Draw", "Away")."""
    return max(probs.items(), key=lambda x: x[1])[0]


def group_winner_probability(group_teams: list[str]) -> Dict[str, float]:
    """Estimate group-winner probabilities.

    When the BT artifact is loaded, softmaxes the fitted strengths (with the
    same temperature scale used for the original FIFA-Elo path so the
    distribution shape stays comparable). Otherwise falls back to softmax
    over FIFA-Elo ratings.

    Args:
        group_teams: Iterable of team names in the group.

    Returns:
        Dict mapping team name -> winner probability (sums to 1.0). Returns
        an empty dict if `group_teams` is empty.
    """
    teams = list(group_teams)
    if not teams:
        return {}

    if _BT_ARTIFACT is not None and all(_has_enough_bt_evidence(t) for t in teams):
        canonicals = [(_canonical(t) or t) for t in teams]
        # BT strength is already in log-space; just normalise via softmax with
        # a temperature of 1.0 (strengths have std ≈ 1.0 from the fit, so this
        # gives realistically-spread probabilities).
        strengths = [_BT_ARTIFACT.strengths[c] for c in canonicals]
        max_s = max(strengths)
        exps = [math.exp(s - max_s) for s in strengths]
        z = sum(exps)
        return {team: e / z for team, e in zip(teams, exps)}

    # Fallback: softmax over FIFA-Elo (the Phase 1 implementation).
    elos = {t: rank_to_elo(get_rank(t)) for t in teams}
    temperature = 200.0
    max_elo = max(elos.values())
    exps = {t: math.exp((e - max_elo) / temperature) for t, e in elos.items()}
    z = sum(exps.values())
    return {t: v / z for t, v in exps.items()}

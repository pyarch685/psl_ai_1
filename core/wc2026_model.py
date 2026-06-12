"""
Davidson-Bradley-Terry model for WC2026 match prediction.

The model assigns each WC2026 team a latent log-strength θᵢ and shares a
single log-draw parameter ν. For an unordered match between teams i and j:

    s_i = exp(θᵢ)
    s_j = exp(θⱼ)
    s_d = exp(ν + (θᵢ + θⱼ) / 2)
    Z   = s_i + s_j + s_d

    P(i wins) = s_i / Z
    P(j wins) = s_j / Z
    P(draw)   = s_d / Z

The draw term uses the geometric mean of the two strengths, so closely matched
sides have a higher draw share than mismatched ones — matching the empirical
behaviour of international football.

Training maximises the multinomial log-likelihood over all H2H aggregates with
L2 regularisation on the strength vector. The regulariser:

  - Anchors the centre of the strength scale (otherwise it is unidentifiable —
    adding a constant to every θᵢ leaves probabilities unchanged).
  - Smoothly shrinks weakly-observed teams toward the mean (e.g. Curacao has
    zero matches in our dataset; its θ ends up at 0 by construction).

We use `scipy.optimize.minimize` with L-BFGS-B against the analytic gradient.
Fits in well under a second on 47-48 teams.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import joblib
import numpy as np
from scipy.optimize import minimize

from core.wc2026_dataset import H2HRow, collect_teams

logger = logging.getLogger(__name__)


MODEL_VERSION: str = "wc2026_davidson_bt_v1"


# Sensible defaults — chosen so that on the WC2026 dataset (671 nonzero pairs,
# 2356 matches) the fit converges in <100 iterations and produces well-spread
# strengths.
DEFAULT_L2: float = 0.5
DEFAULT_DRAW_INIT: float = math.log(0.30)  # start near the empirical draw rate
DEFAULT_MAX_ITER: int = 500


@dataclass
class BTArtifact:
    """Trained Davidson-BT artifact, persistable via joblib."""

    teams: List[str]
    strengths: Dict[str, float]
    # Total observed matches per team (sums across all opponents). Cold-start
    # teams (those absent from the training data) carry a count of zero so
    # the prediction layer can gate BT use on minimum evidence.
    n_matches_per_team: Dict[str, int]
    draw_param: float
    l2: float
    n_matches: int
    n_pairs: int
    final_nll: float
    model_version: str = MODEL_VERSION
    # `metadata` is intentionally permissive — it already mixes numeric fit
    # diagnostics (`iterations`, `theta_std`, `success`) with nested dicts
    # such as `evaluation` (set by `core.wc2026_train.run`) and is consumed
    # by the API layer for the /wc2026/model/status response.
    metadata: Dict[str, Any] = field(default_factory=dict)


def _matches_per_team(rows: List[H2HRow], teams: Sequence[str]) -> Dict[str, int]:
    """Sum observed matches per team across all H2H rows.

    Teams listed in `teams` but absent from the data get an explicit zero so
    the consumer can gate behaviour on evidence without doing a .get() dance.
    """
    counts: Dict[str, int] = {t: 0 for t in teams}
    for r in rows:
        counts[r.team_i] = counts.get(r.team_i, 0) + r.total_matches
        counts[r.team_j] = counts.get(r.team_j, 0) + r.total_matches
    return counts


def _build_index(teams: Sequence[str]) -> Dict[str, int]:
    return {t: i for i, t in enumerate(teams)}


def _predict_probs(theta_i: float, theta_j: float, nu: float) -> Dict[str, float]:
    """Davidson-BT probabilities for a single matchup (numerically stable)."""
    logits = np.array([theta_i, theta_j, nu + 0.5 * (theta_i + theta_j)])
    m = logits.max()
    e = np.exp(logits - m)
    z = e.sum()
    return {"Home": float(e[0] / z), "Away": float(e[1] / z), "Draw": float(e[2] / z)}


def _neg_log_likelihood(
    params: np.ndarray,
    h2h_arr: np.ndarray,  # int matrix: [n_pairs, 5] => i_idx, j_idx, w_i, d, w_j
    l2: float,
    n_teams: int,
) -> tuple[float, np.ndarray]:
    """Vectorised NLL + gradient under the Davidson-BT likelihood.

    The closed-form gradient lets L-BFGS-B converge cleanly without finite
    differences.
    """
    theta = params[:n_teams]
    nu = params[n_teams]

    i_idx = h2h_arr[:, 0]
    j_idx = h2h_arr[:, 1]
    w_i = h2h_arr[:, 2].astype(float)
    d = h2h_arr[:, 3].astype(float)
    w_j = h2h_arr[:, 4].astype(float)

    theta_i = theta[i_idx]
    theta_j = theta[j_idx]
    theta_mid = 0.5 * (theta_i + theta_j)

    logits = np.stack([theta_i, theta_j, nu + theta_mid], axis=1)  # [n, 3]
    m = logits.max(axis=1, keepdims=True)
    e = np.exp(logits - m)
    z = e.sum(axis=1, keepdims=True)
    p = e / z  # [n, 3] columns: home, away, draw

    log_z = np.log(z).squeeze(-1) + m.squeeze(-1)
    log_p_home = theta_i - log_z
    log_p_away = theta_j - log_z
    log_p_draw = (nu + theta_mid) - log_z

    ll = (w_i * log_p_home + w_j * log_p_away + d * log_p_draw).sum()
    nll = -ll + 0.5 * l2 * np.dot(theta, theta)

    # ---- Gradient -----------------------------------------------------------
    n = h2h_arr.shape[0]
    matches = w_i + d + w_j  # [n]

    # dNLL/dθ_i contributions from each pair (the gradient w.r.t. theta_i is
    # observed minus expected over the pair's `matches`):
    #   expected_wins_for_i  = p_home * matches
    #   expected_draws_for_i_half = 0.5 * p_draw * matches  (draw term contributes 0.5 to each)
    #
    # The gradient of -log p_home w.r.t. θ_i is -(1 - p_home), and the
    # gradient of -log p_draw w.r.t. θ_i is -0.5 - (-(p_home + 0.5*p_draw))
    # → after algebra: ∂NLL/∂θ_i = (p_home + 0.5*p_draw) * matches - (w_i + 0.5*d).
    p_home = p[:, 0]
    p_away = p[:, 1]
    p_draw = p[:, 2]

    grad_i = (p_home + 0.5 * p_draw) * matches - (w_i + 0.5 * d)
    grad_j = (p_away + 0.5 * p_draw) * matches - (w_j + 0.5 * d)

    grad_theta = np.zeros(n_teams)
    np.add.at(grad_theta, i_idx, grad_i)
    np.add.at(grad_theta, j_idx, grad_j)
    grad_theta += l2 * theta

    grad_nu = float(((p_draw * matches) - d).sum())

    grad = np.concatenate([grad_theta, [grad_nu]])
    return float(nll), grad


def fit_davidson_bt(
    rows: List[H2HRow],
    l2: float = DEFAULT_L2,
    draw_init: float = DEFAULT_DRAW_INIT,
    max_iter: int = DEFAULT_MAX_ITER,
    teams: Optional[List[str]] = None,
) -> BTArtifact:
    """Fit the Davidson-BT model by L-BFGS-B max-likelihood.

    Args:
        rows: Loaded H2H rows (canonical team names).
        l2: Strength-prior precision; higher = more shrinkage toward 0.
        draw_init: Initial log-draw parameter. Defaults to log(0.30).
        max_iter: L-BFGS-B iteration cap.
        teams: Optional explicit team list (use to include known WC2026 teams
            that have zero matches in the data — they'll keep strength 0).

    Returns:
        A `BTArtifact` containing the fit and metadata.
    """
    observed_teams = collect_teams(rows)
    if teams is None:
        teams = observed_teams
    else:
        # Ensure every observed team is present in the explicit list — fitting
        # blows up if a row references an unindexed team.
        missing = [t for t in observed_teams if t not in teams]
        if missing:
            raise ValueError(
                f"Explicit teams list is missing observed teams: {missing[:5]}…"
            )

    index = _build_index(teams)
    n_teams = len(teams)
    h2h_arr = np.array(
        [
            [index[r.team_i], index[r.team_j], r.wins_i, r.draws, r.wins_j]
            for r in rows
        ],
        dtype=np.int64,
    )

    x0 = np.zeros(n_teams + 1)
    x0[-1] = draw_init

    result = minimize(
        fun=lambda x: _neg_log_likelihood(x, h2h_arr, l2, n_teams),
        x0=x0,
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": max_iter, "ftol": 1e-8, "gtol": 1e-6},
    )

    if not result.success:
        logger.warning("L-BFGS-B did not converge cleanly: %s", result.message)

    theta = result.x[:n_teams]
    nu = float(result.x[n_teams])

    # Centre the strengths so they're identifiable & interpretable. The
    # Davidson likelihood is invariant to a constant added to every θ_i; we
    # normalise to mean-zero so positive θ ⇔ above-average strength.
    theta_mean = float(theta.mean())
    theta = theta - theta_mean

    strengths = {team: float(theta[idx]) for team, idx in index.items()}
    matches_per_team = _matches_per_team(rows, teams)

    n_matches = int(sum(r.total_matches for r in rows))
    artifact = BTArtifact(
        teams=teams,
        strengths=strengths,
        n_matches_per_team=matches_per_team,
        draw_param=nu,
        l2=l2,
        n_matches=n_matches,
        n_pairs=len(rows),
        final_nll=float(result.fun),
        metadata={
            "iterations": float(result.nit),
            "theta_mean_before_centering": theta_mean,
            "theta_std": float(np.std(list(strengths.values()))),
        },
    )
    return artifact


def predict_probs(
    artifact: BTArtifact,
    home_team: str,
    away_team: str,
) -> Dict[str, float]:
    """Predict outcome probabilities for an arbitrary matchup.

    Unknown teams (not in `artifact.teams`) fall back to strength 0 — i.e.
    "average team". The caller (`core.wc2026_prediction.predict`) is expected
    to reject unknown teams *before* this point via `fifa_rankings.has_rank`,
    so this is purely defensive.

    Returns dict with keys "Home", "Draw", "Away" summing to 1.0.
    """
    theta_i = artifact.strengths.get(home_team, 0.0)
    theta_j = artifact.strengths.get(away_team, 0.0)
    return _predict_probs(theta_i, theta_j, artifact.draw_param)


def evaluate(artifact: BTArtifact, rows: List[H2HRow]) -> Dict[str, float]:
    """Compute headline metrics over the training set.

    Returns dict with `log_loss`, `accuracy`, `brier`, `pred_draw_rate`. All
    metrics are weighted by the number of matches per pair (so popular
    matchups dominate, as in the likelihood).
    """
    total_matches = 0
    log_loss_sum = 0.0
    brier_sum = 0.0
    correct = 0
    pred_draws = 0

    for r in rows:
        probs = predict_probs(artifact, r.team_i, r.team_j)
        ph, pd, pa = probs["Home"], probs["Draw"], probs["Away"]

        n = r.wins_i + r.draws + r.wins_j
        total_matches += n

        log_loss_sum -= r.wins_i * math.log(max(ph, 1e-12))
        log_loss_sum -= r.draws * math.log(max(pd, 1e-12))
        log_loss_sum -= r.wins_j * math.log(max(pa, 1e-12))

        # Brier score with one-hot weighting per outcome
        brier_sum += r.wins_i * ((1 - ph) ** 2 + pd**2 + pa**2)
        brier_sum += r.draws * (ph**2 + (1 - pd) ** 2 + pa**2)
        brier_sum += r.wins_j * (ph**2 + pd**2 + (1 - pa) ** 2)

        # "predicted" outcome = argmax — used for accuracy
        predicted = max(probs.items(), key=lambda kv: kv[1])[0]
        if predicted == "Home":
            correct += r.wins_i
            pred_draws += 0
        elif predicted == "Away":
            correct += r.wins_j
        else:
            correct += r.draws
            pred_draws += n

    return {
        "log_loss": log_loss_sum / max(total_matches, 1),
        "accuracy": correct / max(total_matches, 1),
        "brier": brier_sum / max(total_matches, 1),
        "pred_draw_rate": pred_draws / max(total_matches, 1),
        "n_matches": total_matches,
    }


def save_artifact(artifact: BTArtifact, path: Path) -> None:
    """Persist a `BTArtifact` to disk via joblib."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)
    logger.info("Saved WC2026 BT artifact to %s", path)


def load_artifact(path: Path) -> BTArtifact:
    """Load a previously trained `BTArtifact` from disk."""
    artifact = joblib.load(path)
    if not isinstance(artifact, BTArtifact):
        raise TypeError(
            f"Expected BTArtifact at {path}, got {type(artifact).__name__}"
        )
    return artifact

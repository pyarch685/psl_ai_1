"""
Train the WC2026 Davidson-Bradley-Terry model from the H2H aggregate CSV.

Usage (from the repo root):

    python3 -m core.wc2026_train
    python3 -m core.wc2026_train --l2 0.25 --out data/models/wc2026_bt.joblib

Outputs:

    1. A joblib-pickled `BTArtifact` at `--out` (default
       data/models/wc2026_bt.joblib).
    2. A console report with headline metrics (log-loss, accuracy, predicted
       draw rate), top/bottom 5 teams by fitted strength, and a few sanity
       matchup probabilities (Argentina vs Saudi Arabia, Brazil vs USA, etc.).

The CLI is deterministic: given the same input data and `--l2`, the fitted
strengths are reproducible to ~1e-6.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from core.fifa_rankings import _canonical
from core.wc2026_dataset import (
    DEFAULT_DATA_PATH,
    H2HRow,
    collect_teams,
    load_h2h_rows,
    summary,
)
from core.wc2026_model import (
    BTArtifact,
    DEFAULT_L2,
    evaluate,
    fit_davidson_bt,
    predict_probs,
    save_artifact,
)


logger = logging.getLogger(__name__)

DEFAULT_OUT: Path = (
    Path(__file__).resolve().parents[1] / "data" / "models" / "wc2026_bt.joblib"
)

# Canonical list of the 48 WC2026 qualified teams (canonicalised through the
# FIFA alias table). Used to force-include cold-start teams (e.g. Curacao,
# which has zero H2H matches in our 2006-2026 dataset) so the artifact still
# carries an entry for them. Their fitted strength settles at 0 thanks to L2
# regularisation, and the prediction layer falls back to FIFA-Elo when a team
# has fewer than `MIN_MATCHES_FOR_BT` observed matches.
WC2026_TEAMS_FILE: Path = (
    Path(__file__).resolve().parents[1] / "data" / "wc2026_48_teams_used.csv"
)


def _load_wc2026_team_list() -> List[str]:
    """Read the 48-team list, canonicalise, and dedupe (alphabetical)."""
    if not WC2026_TEAMS_FILE.exists():
        return []
    teams = set()
    with WC2026_TEAMS_FILE.open() as fh:
        for raw in fh:
            cleaned = raw.strip()
            if not cleaned:
                continue
            canonical = _canonical(cleaned) or cleaned
            teams.add(canonical)
    return sorted(teams)


# Sanity matchups printed at the end of training. These pairs were not
# specially chosen — they're well-known prior expectations (a top-tier nation
# vs a clearly weaker one, a derby with similar strength, a cold-start team).
SANITY_MATCHUPS = [
    ("Argentina", "Saudi Arabia"),
    ("Brazil", "USA"),
    ("France", "Canada"),
    ("Germany", "Cabo Verde"),
    ("Spain", "Portugal"),
    ("Mexico", "Korea Republic"),
    ("Curacao", "Brazil"),  # cold-start vs top tier
]


def _print_strength_summary(artifact: BTArtifact, top_n: int = 5) -> None:
    """Pretty-print top and bottom teams by fitted log-strength."""
    sorted_teams = sorted(
        artifact.strengths.items(), key=lambda kv: kv[1], reverse=True
    )
    print(f"\nTop {top_n} teams by fitted strength (log-units):")
    for team, theta in sorted_teams[:top_n]:
        print(f"  {team:30s}  θ={theta:+.3f}")
    print(f"Bottom {top_n} teams by fitted strength:")
    for team, theta in sorted_teams[-top_n:]:
        print(f"  {team:30s}  θ={theta:+.3f}")


def _print_sanity_matchups(artifact: BTArtifact) -> None:
    """Print probabilities for the canonical sanity matchups."""
    print("\nSanity matchups (Home / Draw / Away):")
    for home, away in SANITY_MATCHUPS:
        if home not in artifact.strengths or away not in artifact.strengths:
            print(f"  {home} vs {away}: SKIPPED (team not in artifact)")
            continue
        probs = predict_probs(artifact, home, away)
        print(
            f"  {home:18s} vs {away:18s}  "
            f"{probs['Home']:.3f} / {probs['Draw']:.3f} / {probs['Away']:.3f}"
        )


def run(
    data_path: Path = DEFAULT_DATA_PATH,
    out_path: Path = DEFAULT_OUT,
    l2: float = DEFAULT_L2,
    teams_override: List[str] | None = None,
) -> BTArtifact:
    """Load the dataset, fit the model, evaluate, save, and return the artifact."""
    rows = load_h2h_rows(data_path)
    s = summary(rows)
    print(
        f"Dataset: {s['rows']} pairs, {s['matches']} matches, "
        f"{s['teams']} teams, draw_rate={s['draw_rate']:.3f}, "
        f"team_i_win={s['p_team_i']:.3f}, team_j_win={s['p_team_j']:.3f}"
    )

    if teams_override is not None:
        teams = teams_override
    else:
        # Union of (teams observed in the H2H data) and (canonical WC2026 list).
        # Cold-start teams settle at strength 0 via L2 regularisation; the
        # prediction layer detects them via `n_matches_per_team` and routes
        # through FIFA-Elo Phase 1 instead.
        teams = sorted(set(collect_teams(rows)) | set(_load_wc2026_team_list()))

    artifact = fit_davidson_bt(rows, l2=l2, teams=teams)

    metrics = evaluate(artifact, rows)
    # Bake the evaluation result into the artifact's metadata so the API
    # layer can surface real numbers via /wc2026/model/status without
    # re-running evaluate() on every request. Kind is "in_sample" because
    # we score against the same rows we fit on; a chronological holdout
    # split is a deliberate follow-up.
    artifact.metadata["evaluation"] = {
        "accuracy": float(metrics["accuracy"]),
        "log_loss": float(metrics["log_loss"]),
        "brier": float(metrics["brier"]),
        "pred_draw_rate": float(metrics["pred_draw_rate"]),
        "n_matches": int(metrics["n_matches"]),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_kind": "in_sample",
    }
    print(
        f"\nFit complete:"
        f"\n  final NLL: {artifact.final_nll:.2f}"
        f"\n  iterations: {int(artifact.metadata.get('iterations', 0))}"
        f"\n  draw param (ν): {artifact.draw_param:+.4f}"
        f"\n  strength std (post-centering): {artifact.metadata['theta_std']:.3f}"
        f"\n  in-sample log-loss: {metrics['log_loss']:.4f}"
        f"\n  in-sample accuracy: {metrics['accuracy']:.4f}"
        f"\n  in-sample brier:    {metrics['brier']:.4f}"
        f"\n  predicted draw rate: {metrics['pred_draw_rate']:.4f} "
        f"(empirical: {s['draw_rate']:.4f})"
    )

    _print_strength_summary(artifact)
    _print_sanity_matchups(artifact)

    save_artifact(artifact, out_path)
    print(f"\nArtifact saved to: {out_path}")
    return artifact


def main(argv: List[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Train WC2026 Davidson-BT model.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help="Path to the H2H aggregate CSV.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Output joblib artifact path.",
    )
    parser.add_argument(
        "--l2",
        type=float,
        default=DEFAULT_L2,
        help="L2 regularisation strength on the team-strength vector.",
    )
    args = parser.parse_args(argv)

    try:
        run(data_path=args.data, out_path=args.out, l2=args.l2)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

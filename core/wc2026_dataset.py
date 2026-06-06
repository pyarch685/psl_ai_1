"""
Dataset loader for the WC2026 Phase 2 model.

Source: `data/wc2026_48_teams_h2h_summary_2006_2026.csv` — pairwise head-to-head
aggregates between the 48 qualified nations over international matches
2006-2026. Schema (columns the model uses):

    team_a, team_b, matches_2006_2026,
    team_a_wins, draws, team_b_wins,
    goals_a, goals_b

Each row is one unordered pair (i, j); the dataset is symmetric in the sense
that "team_a" / "team_b" is just an alphabetical ordering and carries no home/
neutral semantics. The Davidson-Bradley-Terry fit treats each row as an
exchangeable contest with `team_a_wins + draws + team_b_wins` total matches.

The loader:

- Canonicalises every team name through `core.fifa_rankings._canonical`, which
  maps source strings like "Cape Verde", "Czech Republic", "South Korea",
  "Iran", "Turkey", "Ivory Coast", "Curaçao" to their FIFA-canonical
  equivalents used elsewhere in the codebase ("Cabo Verde", "Czechia",
  "Korea Republic", "IR Iran", "Türkiye", "Côte d'Ivoire", "Curacao").

- Drops zero-match rows (no information for ML).

- Drops accidental self-pairs (the source data shouldn't contain any, but the
  check is cheap and protects the fit).
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from core.fifa_rankings import _canonical

logger = logging.getLogger(__name__)


# Default dataset location relative to the repo root.
DEFAULT_DATA_PATH: Path = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "wc2026_48_teams_h2h_summary_2006_2026.csv"
)


@dataclass(frozen=True)
class H2HRow:
    """A single pairwise head-to-head aggregate.

    `team_i` / `team_j` are canonicalised FIFA names. Counts are non-negative
    integers; `wins_i + draws + wins_j` equals the total number of recorded
    matches between the pair.
    """

    team_i: str
    team_j: str
    wins_i: int
    draws: int
    wins_j: int

    @property
    def total_matches(self) -> int:
        return self.wins_i + self.draws + self.wins_j


def load_h2h_rows(path: Optional[Path] = None) -> List[H2HRow]:
    """Load and canonicalise H2H rows from the WC2026 dataset.

    Args:
        path: Optional override for the CSV path. Defaults to
            `data/wc2026_48_teams_h2h_summary_2006_2026.csv`.

    Returns:
        List of `H2HRow` with FIFA-canonical team names and only the columns
        the model needs. Zero-match and self-pair rows are excluded.

    Raises:
        FileNotFoundError: If the dataset is missing on disk.
        ValueError: If a row has malformed integer fields.
    """
    csv_path = Path(path) if path is not None else DEFAULT_DATA_PATH
    if not csv_path.exists():
        raise FileNotFoundError(
            f"WC2026 H2H dataset not found at {csv_path}. "
            "Make sure data/wc2026_48_teams_h2h_summary_2006_2026.csv is checked in."
        )

    rows: List[H2HRow] = []
    skipped_zero = 0
    skipped_self = 0

    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            try:
                total = int(raw["matches_2006_2026"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Bad matches_2006_2026 value in row {raw!r}: {exc}"
                )
            if total <= 0:
                skipped_zero += 1
                continue

            team_i = _canonical(raw["team_a"]) or raw["team_a"].strip()
            team_j = _canonical(raw["team_b"]) or raw["team_b"].strip()
            if team_i == team_j or not team_i or not team_j:
                skipped_self += 1
                continue

            try:
                wins_i = int(raw["team_a_wins"])
                draws = int(raw["draws"])
                wins_j = int(raw["team_b_wins"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Bad win/draw counts in row {raw!r}: {exc}")

            if wins_i + draws + wins_j != total:
                # The dataset is hand-curated — be defensive but don't crash;
                # the fit uses the per-outcome counts, not the total.
                logger.warning(
                    "H2H row totals don't add up for %s vs %s: w_i=%d d=%d w_j=%d total=%d",
                    team_i,
                    team_j,
                    wins_i,
                    draws,
                    wins_j,
                    total,
                )

            rows.append(
                H2HRow(
                    team_i=team_i,
                    team_j=team_j,
                    wins_i=wins_i,
                    draws=draws,
                    wins_j=wins_j,
                )
            )

    logger.info(
        "Loaded %d H2H rows (skipped %d zero-match, %d self-pair)",
        len(rows),
        skipped_zero,
        skipped_self,
    )
    return rows


def collect_teams(rows: Iterable[H2HRow]) -> List[str]:
    """Return the sorted unique team list across the H2H rows."""
    teams = set()
    for r in rows:
        teams.add(r.team_i)
        teams.add(r.team_j)
    return sorted(teams)


def summary(rows: List[H2HRow]) -> dict:
    """Lightweight summary stats — useful for the training CLI's log line."""
    total = sum(r.total_matches for r in rows)
    if total == 0:
        return {"rows": 0, "matches": 0, "draw_rate": 0.0}

    draws = sum(r.draws for r in rows)
    wins_i = sum(r.wins_i for r in rows)
    wins_j = sum(r.wins_j for r in rows)
    return {
        "rows": len(rows),
        "matches": total,
        "draw_rate": draws / total,
        "p_team_i": wins_i / total,
        "p_team_j": wins_j / total,
        "teams": len(collect_teams(rows)),
    }

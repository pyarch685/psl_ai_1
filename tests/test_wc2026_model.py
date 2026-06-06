"""
Tests for the WC2026 Phase 2 Davidson-Bradley-Terry model.

Covers three layers:

1. `core.wc2026_dataset` — CSV loader + canonicalisation.
2. `core.wc2026_model` — Davidson-BT fit, predict_probs, save/load roundtrip.
3. `core.wc2026_prediction` — public predict() routing (BT when both teams
   have enough evidence, FIFA-Elo fallback otherwise).

The Phase 1 FIFA-Elo behaviour is already covered by
`tests/test_wc2026_prediction.py` — this file focuses on the new BT pieces
and the routing logic added in the refactor.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core.wc2026_dataset import H2HRow, collect_teams, load_h2h_rows, summary
from core.wc2026_model import (
    BTArtifact,
    MODEL_VERSION,
    _matches_per_team,
    evaluate,
    fit_davidson_bt,
    load_artifact,
    predict_probs,
    save_artifact,
)


# ---------- Dataset loader ---------------------------------------------------


def test_dataset_loads_with_canonical_names():
    """Source CSV uses 'Cape Verde', 'Czech Republic', etc. — loader must
    canonicalise to the FIFA-canonical names used by the rest of the app."""
    rows = load_h2h_rows()
    teams = set(collect_teams(rows))
    # The source CSV has 'Cape Verde' — canonical is 'Cabo Verde'.
    assert "Cabo Verde" in teams
    assert "Cape Verde" not in teams
    # Same for the other common renames.
    assert "Czechia" in teams
    assert "Czech Republic" not in teams
    assert "Korea Republic" in teams
    assert "South Korea" not in teams
    assert "USA" in teams
    assert "United States" not in teams


def test_dataset_summary_has_expected_shape():
    """Sanity check on the empirical statistics — guards against accidental
    data corruption in the committed CSV."""
    rows = load_h2h_rows()
    s = summary(rows)
    # 48 qualified teams, but Curacao has zero H2H matches so the nonzero
    # rows only cover 47 distinct teams.
    assert s["teams"] == 47
    assert s["rows"] >= 600  # 671 actual; allow drift on future CSV updates
    assert 0.20 <= s["draw_rate"] <= 0.30  # international draw rate is ~25%
    # team_i and team_j are alphabetical, not home/away — proportions should
    # be roughly balanced (within ±10pp).
    assert abs(s["p_team_i"] - s["p_team_j"]) < 0.10


def test_h2hrow_total_matches():
    row = H2HRow(team_i="A", team_j="B", wins_i=3, draws=2, wins_j=4)
    assert row.total_matches == 9


# ---------- Davidson-BT fit --------------------------------------------------


def test_fit_recovers_strength_ordering_on_synthetic_data():
    """With clean synthetic data, the BT fit must recover the team ordering.

    Three teams: Strong (>) Mid (>) Weak. Construct H2H rows from a Davidson
    likelihood with known strengths; the recovered ordering must match.
    """
    rng_rows = [
        H2HRow("Strong", "Mid", wins_i=14, draws=4, wins_j=2),
        H2HRow("Strong", "Weak", wins_i=18, draws=1, wins_j=1),
        H2HRow("Mid", "Weak", wins_i=12, draws=4, wins_j=4),
    ]
    artifact = fit_davidson_bt(rng_rows, l2=0.1)
    s = artifact.strengths
    assert s["Strong"] > s["Mid"] > s["Weak"]
    # Strengths are centered (mean zero) by the fit.
    assert abs(sum(s.values())) < 1e-6


def test_predict_probs_sums_to_one_and_returns_three_keys():
    rows = [
        H2HRow("Strong", "Mid", wins_i=14, draws=4, wins_j=2),
        H2HRow("Strong", "Weak", wins_i=18, draws=1, wins_j=1),
        H2HRow("Mid", "Weak", wins_i=12, draws=4, wins_j=4),
    ]
    artifact = fit_davidson_bt(rows, l2=0.1)
    probs = predict_probs(artifact, "Strong", "Weak")
    assert set(probs.keys()) == {"Home", "Draw", "Away"}
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert probs["Home"] > probs["Away"]


def test_predict_probs_handles_unknown_team_via_zero_strength():
    """An unknown team is treated as strength 0 (= mean). This is purely a
    defence-in-depth check — the public `predict()` in
    `core.wc2026_prediction` filters unknowns out *before* hitting the BT
    model via the FIFA-Elo fallback."""
    rows = [
        H2HRow("Strong", "Mid", wins_i=14, draws=4, wins_j=2),
        H2HRow("Strong", "Weak", wins_i=18, draws=1, wins_j=1),
        H2HRow("Mid", "Weak", wins_i=12, draws=4, wins_j=4),
    ]
    artifact = fit_davidson_bt(rows, l2=0.1)
    probs = predict_probs(artifact, "Strong", "NotInArtifact")
    # "Strong" should still be favoured against a strength-0 unknown.
    assert probs["Home"] > probs["Away"]
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_fit_includes_cold_start_teams_when_listed_explicitly():
    """`teams=` override forces a team into the artifact even if it has zero
    rows in the data — used at training time to add Curacao."""
    rows = [
        H2HRow("Strong", "Mid", wins_i=10, draws=2, wins_j=2),
    ]
    artifact = fit_davidson_bt(rows, l2=0.5, teams=["Strong", "Mid", "Coldstart"])
    assert "Coldstart" in artifact.strengths
    # Cold-start team's strength settles at the L2 anchor (≈ 0 after centering).
    assert abs(artifact.strengths["Coldstart"]) < 0.5
    # Its match count must be zero in the artifact.
    assert artifact.n_matches_per_team["Coldstart"] == 0


def test_fit_raises_when_teams_override_misses_observed_team():
    """The fit must reject a `teams=` list that omits a team referenced by
    the H2H rows — otherwise the indexing would silently corrupt."""
    rows = [
        H2HRow("Strong", "Mid", wins_i=10, draws=2, wins_j=2),
    ]
    with pytest.raises(ValueError):
        fit_davidson_bt(rows, l2=0.5, teams=["Strong"])  # missing "Mid"


def test_save_load_roundtrip(tmp_path):
    rows = [
        H2HRow("Strong", "Mid", wins_i=14, draws=4, wins_j=2),
        H2HRow("Strong", "Weak", wins_i=18, draws=1, wins_j=1),
        H2HRow("Mid", "Weak", wins_i=12, draws=4, wins_j=4),
    ]
    artifact = fit_davidson_bt(rows, l2=0.1)
    path = tmp_path / "bt.joblib"
    save_artifact(artifact, path)
    reloaded = load_artifact(path)
    assert reloaded.model_version == MODEL_VERSION
    assert reloaded.strengths == artifact.strengths
    assert reloaded.draw_param == artifact.draw_param
    # Predictions identical post-roundtrip.
    p1 = predict_probs(artifact, "Strong", "Weak")
    p2 = predict_probs(reloaded, "Strong", "Weak")
    for k in p1:
        assert abs(p1[k] - p2[k]) < 1e-12


def test_evaluate_returns_finite_metrics_on_real_data():
    """Smoke test the evaluator against the committed dataset."""
    rows = load_h2h_rows()
    teams = sorted(set(collect_teams(rows)))
    artifact = fit_davidson_bt(rows, l2=0.5, teams=teams)
    metrics = evaluate(artifact, rows)
    assert math.isfinite(metrics["log_loss"])
    assert 0.0 < metrics["accuracy"] < 1.0
    assert 0.0 < metrics["brier"] < 2.0
    # Log-loss for 3-way classification under a uniform predictor is log(3)
    # ≈ 1.0986. The model must outperform that.
    assert metrics["log_loss"] < math.log(3.0)


# ---------- Predict-layer routing -------------------------------------------


def test_prediction_layer_uses_bt_when_artifact_present(tmp_path):
    """When the trained artifact is present, predictions must come from the
    Davidson-BT model (not the FIFA-Elo fallback)."""
    from core import wc2026_prediction as wp

    if wp._BT_ARTIFACT is None:
        pytest.skip("BT artifact unavailable in this environment")

    # Argentina vs Saudi Arabia is a well-observed matchup — the BT model
    # gives ~78% home / 16% draw / 6% away. FIFA-Elo would give a much
    # smaller home edge (~65%). Distinguishing the two confirms BT is live.
    probs = wp.predict("Argentina", "Saudi Arabia")
    assert probs["Home"] > 0.70  # BT range
    assert probs["Away"] < 0.10
    # Probabilities must always sum to 1.
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_prediction_layer_falls_back_to_elo_for_cold_start():
    """Curacao has zero matches in the dataset — predictions involving it
    must route through the Phase 1 FIFA-Elo fallback, not the BT artifact.
    """
    from core import wc2026_prediction as wp

    if wp._BT_ARTIFACT is None:
        pytest.skip("BT artifact unavailable in this environment")

    # Brazil vs Curacao under BT (Curacao at strength 0) would give about
    # 80% home. Under FIFA-Elo (Curacao at rank ~80, Brazil at rank ~5)
    # the gap is much larger and home probability is ≥ 78%. Both are high
    # but the FIFA-Elo path produces the realistic answer.
    probs_b_vs_c = wp.predict("Brazil", "Curacao")
    # Sanity: Brazil heavily favoured either way.
    assert probs_b_vs_c["Home"] > 0.70
    assert probs_b_vs_c["Away"] < 0.15

    # And the routing helper must report no BT evidence for Curacao.
    assert not wp._has_enough_bt_evidence("Curacao")
    # While Brazil has plenty.
    assert wp._has_enough_bt_evidence("Brazil")


def test_prediction_layer_handles_alias_inputs():
    """Frontend may submit non-canonical names — the routing must
    canonicalise them before BT lookup."""
    from core import wc2026_prediction as wp

    if wp._BT_ARTIFACT is None:
        pytest.skip("BT artifact unavailable in this environment")

    # "South Korea" and "Iran" must route to the BT entries for "Korea
    # Republic" and "IR Iran" respectively.
    probs = wp.predict("South Korea", "Iran")
    assert set(probs.keys()) == {"Home", "Draw", "Away"}
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    # The canonical equivalents must produce identical probabilities.
    canonical = wp.predict("Korea Republic", "IR Iran")
    for k in probs:
        assert abs(probs[k] - canonical[k]) < 1e-12


# ---------- _matches_per_team helper ----------------------------------------


def test_matches_per_team_sums_correctly():
    rows = [
        H2HRow("A", "B", wins_i=3, draws=2, wins_j=4),  # 9 matches
        H2HRow("A", "C", wins_i=1, draws=1, wins_j=2),  # 4 matches
        H2HRow("B", "C", wins_i=2, draws=0, wins_j=0),  # 2 matches
    ]
    counts = _matches_per_team(rows, ["A", "B", "C", "D"])
    assert counts["A"] == 9 + 4  # 13
    assert counts["B"] == 9 + 2  # 11
    assert counts["C"] == 4 + 2  # 6
    assert counts["D"] == 0  # listed but no observations


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

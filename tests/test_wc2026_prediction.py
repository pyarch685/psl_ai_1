"""
Tests for `core.wc2026_prediction` (FIFA-Elo Phase 1 predictor).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core import wc2026_prediction as w
from core.fifa_rankings import FIFA_RANKING, DEFAULT_RANK, get_rank


def _probs_sum_to_one(probs):
    return abs(sum(probs.values()) - 1.0) < 1e-9


def test_predict_returns_three_keys_summing_to_one():
    probs = w.predict("Argentina", "Saudi Arabia")
    assert set(probs.keys()) == {"Home", "Draw", "Away"}
    assert _probs_sum_to_one(probs)


def test_higher_ranked_team_has_higher_win_probability():
    # Argentina (#1) is far stronger than Saudi Arabia (#49).
    probs = w.predict("Argentina", "Saudi Arabia")
    assert probs["Home"] > probs["Away"]
    assert probs["Home"] > 0.55


def test_lower_ranked_team_as_home_still_underdog_when_gap_is_large():
    # New Zealand (#89) at home vs Argentina (#1) — Argentina still favored.
    probs = w.predict("New Zealand", "Argentina")
    assert probs["Away"] > probs["Home"]
    assert probs["Away"] > 0.55


def test_equal_ranked_teams_roughly_equal_probabilities():
    # Same team on both sides ⇒ identical Elo ⇒ Home == Away.
    probs = w.predict("Germany", "Germany")
    assert abs(probs["Home"] - probs["Away"]) < 1e-9
    # Draw share at zero gap == baseline draw share.
    assert probs["Draw"] > 0.25


def test_draw_probability_shrinks_with_larger_gap():
    close = w.predict("Spain", "France")
    far = w.predict("Argentina", "Saudi Arabia")
    assert close["Draw"] > far["Draw"]


def test_unknown_teams_fall_back_to_default_rank():
    # Both teams unknown ⇒ identical default rank ⇒ symmetric probs.
    probs = w.predict("Atlantis", "Wakanda")
    assert abs(probs["Home"] - probs["Away"]) < 1e-9
    assert get_rank("Atlantis") == DEFAULT_RANK
    assert get_rank("Wakanda") == DEFAULT_RANK


def test_alias_resolution_for_common_names():
    # Frontend may send casual names — they must resolve to FIFA-canonical.
    assert get_rank("South Korea") == FIFA_RANKING["Korea Republic"]
    assert get_rank("Czech Republic") == FIFA_RANKING["Czechia"]
    assert get_rank("United States") == FIFA_RANKING["USA"]
    assert get_rank("Turkey") == FIFA_RANKING["Türkiye"]
    assert get_rank("Ivory Coast") == FIFA_RANKING["Côte d'Ivoire"]
    assert get_rank("Cape Verde") == FIFA_RANKING["Cabo Verde"]
    assert get_rank("Iran") == FIFA_RANKING["IR Iran"]
    assert get_rank("DR Congo") == FIFA_RANKING["Congo DR"]


def test_outcome_from_probs_picks_max():
    assert w.outcome_from_probs({"Home": 0.5, "Draw": 0.2, "Away": 0.3}) == "Home"
    assert w.outcome_from_probs({"Home": 0.2, "Draw": 0.5, "Away": 0.3}) == "Draw"
    assert w.outcome_from_probs({"Home": 0.2, "Draw": 0.3, "Away": 0.5}) == "Away"


def test_group_winner_probability_orders_by_strength():
    teams = ["Mexico", "Korea Republic", "Czechia", "South Africa"]
    probs = w.group_winner_probability(teams)
    assert set(probs.keys()) == set(teams)
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    # Mexico (#18) > Korea Republic (#22) > Czechia (#36) > South Africa (#60).
    ordering = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    assert ordering[0][0] == "Mexico"
    assert ordering[-1][0] == "South Africa"


def test_group_winner_probability_handles_empty_input():
    assert w.group_winner_probability([]) == {}


def test_model_version_tag_reflects_active_model():
    """MODEL_VERSION must advertise the model that's actually serving.

    When the Davidson-BT artifact is present at module import the tag must
    advertise `wc2026_davidson_bt_v1`; otherwise it falls back to the
    Phase 1 FIFA-Elo tag (`fifa_elo_v1`). This is the contract the
    prediction-store relies on to provenance-tag persisted rows.
    """
    if w._BT_ARTIFACT is not None:
        assert w.MODEL_VERSION == "wc2026_davidson_bt_v1"
    else:
        assert w.MODEL_VERSION == "fifa_elo_v1"


def test_rank_to_elo_is_monotonic_and_bounded():
    elo_1 = w.rank_to_elo(1)
    elo_50 = w.rank_to_elo(50)
    elo_200 = w.rank_to_elo(200)
    assert elo_1 > elo_50 > elo_200
    assert 1300.0 <= elo_200 <= elo_50 <= elo_1 <= 2100.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

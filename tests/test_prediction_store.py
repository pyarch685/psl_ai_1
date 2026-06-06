"""
Unit tests for ``core.prediction_store``.

These tests run against an in-memory SQLite database with a Postgres-
compatible subset of the schema. ``NOW()`` is registered as a UDF so
the same SQL used in production also runs here.

The tests cover:
- Pure helpers (model_version_label, outcome derivation)
- Insert-only semantics on the predictions table
- Resolve job backfills actual columns and respects ``resolved_at IS NULL``
- ``persist_upcoming_fixture_predictions`` skips quietly when no model is loaded
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Dict

import pandas as pd
import pytest
from sqlalchemy import create_engine, event, text

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core import prediction_store
from core.prediction_store import (
    _outcome_from_probs,
    _outcome_from_score,
    insert_prediction_if_absent,
    model_version_label,
    persist_upcoming_fixture_predictions,
    resolve_completed_predictions,
)


@pytest.fixture
def engine(tmp_path):
    """In-memory SQLite engine with the predictions + fixtures tables."""
    db_path = tmp_path / "test.db"
    eng = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(eng, "connect")
    def _register_now(dbapi_connection, _record):  # pragma: no cover - hook
        dbapi_connection.create_function(
            "NOW", 0, lambda: datetime.utcnow().isoformat(sep=" ")
        )

    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_date DATE NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    home_win_prob REAL NOT NULL,
                    draw_prob REAL NOT NULL,
                    away_win_prob REAL NOT NULL,
                    predicted_outcome TEXT,
                    confidence REAL,
                    model_version TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    actual_outcome TEXT,
                    actual_home_goals INTEGER,
                    actual_away_goals INTEGER,
                    is_correct BOOLEAN,
                    resolved_at TIMESTAMP,
                    UNIQUE (match_date, home_team, away_team)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE fixtures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    venue TEXT,
                    status TEXT NOT NULL DEFAULT 'on schedule',
                    home_goals INTEGER,
                    away_goals INTEGER
                )
                """
            )
        )

    return eng


# ---------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------


def test_model_version_label_includes_key_params():
    fake_model = SimpleNamespace(
        params={
            "model": "Neural Net (MLP)",
            "k": 24.0,
            "window": 6,
            "calibrated": True,
        }
    )
    label = model_version_label(fake_model)
    assert "Neural_Net" in label
    assert "k24" in label
    assert "w6" in label
    assert label.endswith("cal")


def test_outcome_from_probs_picks_max():
    outcome, conf = _outcome_from_probs({"Home": 0.5, "Draw": 0.3, "Away": 0.2})
    assert outcome == "Home"
    assert conf == pytest.approx(0.5)


@pytest.mark.parametrize(
    "hg,ag,expected",
    [(2, 0, "Home"), (1, 1, "Draw"), (0, 3, "Away")],
)
def test_outcome_from_score(hg, ag, expected):
    assert _outcome_from_score(hg, ag) == expected


# ---------------------------------------------------------------------
# Insert-only behaviour
# ---------------------------------------------------------------------


def _probs(home: float, draw: float, away: float) -> Dict[str, float]:
    return {"Home": home, "Draw": draw, "Away": away}


def test_insert_creates_row_with_expected_columns(engine):
    inserted = insert_prediction_if_absent(
        engine=engine,
        match_date=date(2026, 6, 15),
        home_team="Orlando Pirates",
        away_team="Kaizer Chiefs",
        probs=_probs(0.55, 0.25, 0.20),
        model_version="test-v1",
    )
    assert inserted is True

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT home_win_prob, draw_prob, away_win_prob, "
                "predicted_outcome, confidence, model_version "
                "FROM predictions"
            )
        ).fetchone()

    assert row.home_win_prob == pytest.approx(0.55)
    assert row.draw_prob == pytest.approx(0.25)
    assert row.away_win_prob == pytest.approx(0.20)
    assert row.predicted_outcome == "Home"
    assert row.confidence == pytest.approx(0.55)
    assert row.model_version == "test-v1"


def test_insert_duplicate_is_skipped_and_does_not_overwrite(engine):
    insert_prediction_if_absent(
        engine=engine,
        match_date=date(2026, 6, 15),
        home_team="Orlando Pirates",
        away_team="Kaizer Chiefs",
        probs=_probs(0.55, 0.25, 0.20),
        model_version="test-v1",
    )

    # Same fixture, different model version and probabilities — must NOT overwrite.
    inserted_again = insert_prediction_if_absent(
        engine=engine,
        match_date=date(2026, 6, 15),
        home_team="Orlando Pirates",
        away_team="Kaizer Chiefs",
        probs=_probs(0.10, 0.10, 0.80),
        model_version="test-v2",
    )
    assert inserted_again is False

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT home_win_prob, model_version FROM predictions"
            )
        ).fetchone()

    assert row.home_win_prob == pytest.approx(0.55)
    assert row.model_version == "test-v1"


# ---------------------------------------------------------------------
# Resolve behaviour
# ---------------------------------------------------------------------


def _seed_prediction(engine, *, match_date, home, away, predicted="Home"):
    """Insert a prediction row directly for resolve tests."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO predictions (
                    match_date, home_team, away_team,
                    home_win_prob, draw_prob, away_win_prob,
                    predicted_outcome, confidence, model_version
                ) VALUES (
                    :match_date, :home, :away,
                    0.6, 0.2, 0.2,
                    :predicted, 0.6, 'test-v1'
                )
                """
            ),
            {
                "match_date": match_date,
                "home": home,
                "away": away,
                "predicted": predicted,
            },
        )


def _seed_completed_fixture(engine, *, match_date, home, away, hg, ag):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fixtures (
                    date, home_team, away_team, status, home_goals, away_goals
                ) VALUES (
                    :match_date, :home, :away, 'completed', :hg, :ag
                )
                """
            ),
            {
                "match_date": match_date,
                "home": home,
                "away": away,
                "hg": hg,
                "ag": ag,
            },
        )


def test_resolve_sets_actuals_and_marks_correct(engine):
    match_date = date(2026, 5, 10)
    _seed_prediction(
        engine, match_date=match_date, home="A", away="B", predicted="Home"
    )
    _seed_completed_fixture(
        engine, match_date=match_date, home="A", away="B", hg=2, ag=0
    )

    stats = resolve_completed_predictions(engine=engine)
    assert stats["resolved"] == 1

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT actual_outcome, actual_home_goals, actual_away_goals, "
                "is_correct, resolved_at FROM predictions"
            )
        ).fetchone()

    assert row.actual_outcome == "Home"
    assert row.actual_home_goals == 2
    assert row.actual_away_goals == 0
    assert bool(row.is_correct) is True
    assert row.resolved_at is not None


def test_resolve_marks_incorrect_when_prediction_misses(engine):
    match_date = date(2026, 5, 11)
    _seed_prediction(
        engine, match_date=match_date, home="A", away="B", predicted="Home"
    )
    _seed_completed_fixture(
        engine, match_date=match_date, home="A", away="B", hg=0, ag=3
    )

    resolve_completed_predictions(engine=engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT actual_outcome, is_correct FROM predictions")
        ).fetchone()

    assert row.actual_outcome == "Away"
    assert bool(row.is_correct) is False


def test_resolve_is_idempotent(engine):
    match_date = date(2026, 5, 12)
    _seed_prediction(engine, match_date=match_date, home="A", away="B")
    _seed_completed_fixture(
        engine, match_date=match_date, home="A", away="B", hg=1, ag=1
    )

    first = resolve_completed_predictions(engine=engine)
    second = resolve_completed_predictions(engine=engine)

    assert first["resolved"] == 1
    assert second["resolved"] == 0


# ---------------------------------------------------------------------
# Batch persist
# ---------------------------------------------------------------------


def test_persist_skips_when_model_is_none():
    stats = persist_upcoming_fixture_predictions(model=None)
    assert stats == {"considered": 0, "inserted": 0, "skipped": 0, "failed": 0}


def test_persist_inserts_upcoming_fixture(monkeypatch, engine):
    """End-to-end: provided an engine and a stub model, the batch
    persists one row for an upcoming fixture and skips duplicates on rerun."""
    today = pd.Timestamp.today().normalize()
    upcoming_date = today + pd.Timedelta(days=3)

    fake_fixtures = pd.DataFrame(
        [
            {
                "date": upcoming_date,
                "home_team": "Sundowns",
                "away_team": "AmaZulu",
                "venue": "Loftus",
                "status": "on schedule",
                "home_goals": None,
                "away_goals": None,
            },
            {
                # In the past — must be filtered out.
                "date": today - pd.Timedelta(days=5),
                "home_team": "Past Home",
                "away_team": "Past Away",
                "venue": "",
                "status": "completed",
                "home_goals": 1,
                "away_goals": 0,
            },
        ]
    )

    monkeypatch.setattr(prediction_store, "load_fixtures", lambda _t: fake_fixtures)
    monkeypatch.setattr(
        prediction_store,
        "predict_softmax",
        lambda _model, _h, _a: {"Home": 0.5, "Draw": 0.3, "Away": 0.2},
    )

    fake_model = SimpleNamespace(
        params={"model": "Softmax", "k": 24.0, "window": 6, "calibrated": False}
    )

    stats = persist_upcoming_fixture_predictions(fake_model, engine=engine)
    assert stats["inserted"] == 1
    assert stats["considered"] == 1  # past fixture filtered out
    assert stats["skipped"] == 0

    # Rerun — should skip because the row already exists.
    stats_again = persist_upcoming_fixture_predictions(fake_model, engine=engine)
    assert stats_again["inserted"] == 0
    assert stats_again["skipped"] == 1

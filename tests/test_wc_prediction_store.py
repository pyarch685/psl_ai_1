"""
Tests for `core.wc_prediction_store`.

Uses an in-memory SQLite engine and stubs `core.wc2026_prediction.predict`
so the snapshot tests don't depend on a trained BT artifact / FIFA-Elo data.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core import wc2026_prediction  # noqa: E402
from core import wc_prediction_store  # noqa: E402


def _create_test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    schema = """
    CREATE TABLE IF NOT EXISTS wc_fixtures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_date DATE NOT NULL,
        kickoff_time TEXT,
        group_name TEXT,
        stage TEXT NOT NULL DEFAULT 'group',
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        venue TEXT,
        home_goals INTEGER,
        away_goals INTEGER,
        status TEXT NOT NULL DEFAULT 'scheduled',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (match_date, home_team, away_team)
    );

    CREATE TABLE IF NOT EXISTS wc_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixture_id INTEGER NOT NULL UNIQUE,
        predicted_outcome TEXT NOT NULL,
        prob_home REAL NOT NULL,
        prob_draw REAL NOT NULL,
        prob_away REAL NOT NULL,
        confidence REAL NOT NULL,
        model_version TEXT NOT NULL,
        snapshot_kind TEXT NOT NULL,
        predicted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        actual_outcome TEXT,
        actual_home_goals INTEGER,
        actual_away_goals INTEGER,
        is_correct INTEGER,
        resolved_at TIMESTAMP
    );
    """
    with engine.begin() as conn:
        for stmt in schema.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
    return engine


@pytest.fixture
def engine():
    return _create_test_engine()


@pytest.fixture
def stub_predict(monkeypatch):
    """
    Replace `wc2026_prediction.predict` with a deterministic stub so
    snapshot logic is testable without a trained artifact.

    The stub returns Home as the favourite (0.6 / 0.25 / 0.15) regardless
    of teams.
    """
    def _fake_predict(home_team: str, away_team: str):
        return {"Home": 0.6, "Draw": 0.25, "Away": 0.15}

    monkeypatch.setattr(wc2026_prediction, "predict", _fake_predict)
    monkeypatch.setattr(wc2026_prediction, "_model_in_use", lambda: "stub_v1")
    yield


def _seed_fixture(
    engine,
    *,
    match_date: str,
    kickoff_time: str = "20:00",
    home_team: str = "Mexico",
    away_team: str = "Korea Republic",
    home_goals=None,
    away_goals=None,
    status: str = "scheduled",
):
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, home_team, away_team, "
                " home_goals, away_goals, status) "
                "VALUES (:d, :t, :h, :a, :hg, :ag, :s) "
                "RETURNING id"
            ),
            {
                "d": match_date,
                "t": kickoff_time,
                "h": home_team,
                "a": away_team,
                "hg": home_goals,
                "ag": away_goals,
                "s": status,
            },
        )
        return int(result.fetchone()[0])


# --------------------------------------------------------------------------
# snapshot_wc_predictions
# --------------------------------------------------------------------------


def test_snapshot_inserts_pre_match_for_future_fixture(engine, stub_predict):
    future = (datetime.utcnow() + timedelta(days=10)).date().isoformat()
    fixture_id = _seed_fixture(engine, match_date=future, kickoff_time="18:00")

    stats = wc_prediction_store.snapshot_wc_predictions(engine=engine)

    assert stats["considered"] == 1
    assert stats["inserted_pre_match"] == 1
    assert stats["inserted_retroactive"] == 0
    assert stats["failed"] == 0

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM wc_predictions WHERE fixture_id = :fid"),
            {"fid": fixture_id},
        ).mappings().first()
    assert row is not None
    assert row["snapshot_kind"] == "pre_match"
    assert row["predicted_outcome"] == "Home"
    assert pytest.approx(row["prob_home"] + row["prob_draw"] + row["prob_away"], 0.001) == 1.0
    assert row["model_version"] == "stub_v1"


def test_snapshot_inserts_retroactive_for_past_fixture(engine, stub_predict):
    past = (datetime.utcnow() - timedelta(days=5)).date().isoformat()
    fixture_id = _seed_fixture(engine, match_date=past, kickoff_time="18:00")

    stats = wc_prediction_store.snapshot_wc_predictions(engine=engine)
    assert stats["inserted_pre_match"] == 0
    assert stats["inserted_retroactive"] == 1

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT snapshot_kind FROM wc_predictions WHERE fixture_id = :fid"),
            {"fid": fixture_id},
        ).mappings().first()
    assert row["snapshot_kind"] == "retroactive"


def test_snapshot_is_insert_only(engine, stub_predict):
    future = (datetime.utcnow() + timedelta(days=10)).date().isoformat()
    _seed_fixture(engine, match_date=future)

    first = wc_prediction_store.snapshot_wc_predictions(engine=engine)
    second = wc_prediction_store.snapshot_wc_predictions(engine=engine)

    assert first["inserted_pre_match"] == 1
    # Second call sees no unsnapshotted fixtures, so considered drops to 0.
    assert second["considered"] == 0
    assert second["inserted_pre_match"] == 0
    assert second["inserted_retroactive"] == 0


def test_snapshot_kind_locked_after_insert(engine, stub_predict):
    """
    A row inserted as `pre_match` keeps that kind even after kickoff time
    passes. The snapshot job is insert-only and never re-classifies.
    """
    # Pretend "now" is well before kickoff at insert time.
    now_before = datetime(2026, 5, 1, 12, 0, 0)
    fixture_id = _seed_fixture(engine, match_date="2026-06-15", kickoff_time="20:00")

    wc_prediction_store.snapshot_wc_predictions(engine=engine, now=now_before)

    # Now run again pretending we're in the far future. The row should
    # not be touched.
    now_after = datetime(2027, 1, 1, 12, 0, 0)
    wc_prediction_store.snapshot_wc_predictions(engine=engine, now=now_after)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT snapshot_kind FROM wc_predictions WHERE fixture_id = :fid"),
            {"fid": fixture_id},
        ).mappings().first()
    assert row["snapshot_kind"] == "pre_match"


def test_snapshot_skips_fixtures_with_blank_teams(engine, stub_predict):
    future = (datetime.utcnow() + timedelta(days=10)).date().isoformat()
    # Direct insert - the seed helper would reject empty strings via NOT NULL.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, home_team, away_team) "
                "VALUES (:d, '18:00', '', 'Korea Republic')"
            ),
            {"d": future},
        )

    stats = wc_prediction_store.snapshot_wc_predictions(engine=engine)
    assert stats["considered"] == 1
    assert stats["failed"] == 1
    assert stats["inserted_pre_match"] == 0


# --------------------------------------------------------------------------
# backfill_completed_wc_predictions
# --------------------------------------------------------------------------


def test_backfill_resolves_completed(engine, stub_predict):
    past = (datetime.utcnow() - timedelta(days=2)).date().isoformat()
    fixture_id = _seed_fixture(
        engine,
        match_date=past,
        kickoff_time="18:00",
        home_goals=2,
        away_goals=1,
        status="completed",
    )
    wc_prediction_store.snapshot_wc_predictions(engine=engine)

    stats = wc_prediction_store.backfill_completed_wc_predictions(engine=engine)
    assert stats["resolved"] == 1

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT actual_outcome, actual_home_goals, actual_away_goals, "
                "       is_correct, resolved_at "
                "FROM wc_predictions WHERE fixture_id = :fid"
            ),
            {"fid": fixture_id},
        ).mappings().first()
    assert row["actual_outcome"] == "Home"
    assert row["actual_home_goals"] == 2
    assert row["actual_away_goals"] == 1
    # Stub predicted Home; result was Home -> correct.
    assert row["is_correct"] in (1, True)
    assert row["resolved_at"] is not None


def test_backfill_marks_incorrect_when_outcome_differs(engine, stub_predict):
    past = (datetime.utcnow() - timedelta(days=2)).date().isoformat()
    fixture_id = _seed_fixture(
        engine,
        match_date=past,
        kickoff_time="18:00",
        home_goals=0,
        away_goals=2,
        status="completed",
    )
    wc_prediction_store.snapshot_wc_predictions(engine=engine)

    wc_prediction_store.backfill_completed_wc_predictions(engine=engine)

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT actual_outcome, is_correct "
                "FROM wc_predictions WHERE fixture_id = :fid"
            ),
            {"fid": fixture_id},
        ).mappings().first()
    assert row["actual_outcome"] == "Away"
    # Stub predicted Home; actual Away -> incorrect.
    assert row["is_correct"] in (0, False)


def test_backfill_does_not_touch_already_resolved(engine, stub_predict):
    past = (datetime.utcnow() - timedelta(days=2)).date().isoformat()
    fixture_id = _seed_fixture(
        engine,
        match_date=past,
        kickoff_time="18:00",
        home_goals=2,
        away_goals=1,
        status="completed",
    )
    wc_prediction_store.snapshot_wc_predictions(engine=engine)
    wc_prediction_store.backfill_completed_wc_predictions(engine=engine)

    # Capture resolved_at the first time around.
    with engine.connect() as conn:
        first = conn.execute(
            text("SELECT resolved_at FROM wc_predictions WHERE fixture_id = :fid"),
            {"fid": fixture_id},
        ).mappings().first()

    # Backfill again - should be a no-op for this row.
    stats = wc_prediction_store.backfill_completed_wc_predictions(engine=engine)
    assert stats["resolved"] == 0

    with engine.connect() as conn:
        second = conn.execute(
            text("SELECT resolved_at FROM wc_predictions WHERE fixture_id = :fid"),
            {"fid": fixture_id},
        ).mappings().first()
    assert second["resolved_at"] == first["resolved_at"]


def test_backfill_skips_unresolved_fixtures(engine, stub_predict):
    """A scheduled fixture (no scores) must not be backfilled."""
    future = (datetime.utcnow() + timedelta(days=5)).date().isoformat()
    _seed_fixture(engine, match_date=future, kickoff_time="18:00")
    wc_prediction_store.snapshot_wc_predictions(engine=engine)

    stats = wc_prediction_store.backfill_completed_wc_predictions(engine=engine)
    assert stats["resolved"] == 0


# --------------------------------------------------------------------------
# load_resolved_wc_predictions / count_pending_wc_predictions
# --------------------------------------------------------------------------


def test_load_resolved_orders_by_date_desc(engine, stub_predict):
    older = (datetime.utcnow() - timedelta(days=5)).date().isoformat()
    newer = (datetime.utcnow() - timedelta(days=2)).date().isoformat()

    _seed_fixture(
        engine,
        match_date=older,
        home_team="Mexico",
        away_team="South Africa",
        home_goals=1,
        away_goals=0,
        status="completed",
    )
    _seed_fixture(
        engine,
        match_date=newer,
        home_team="Korea Republic",
        away_team="Czechia",
        home_goals=0,
        away_goals=1,
        status="completed",
    )

    wc_prediction_store.snapshot_wc_predictions(engine=engine)
    wc_prediction_store.backfill_completed_wc_predictions(engine=engine)

    rows = wc_prediction_store.load_resolved_wc_predictions(engine=engine)
    assert len(rows) == 2
    # Newest first.
    assert str(rows[0]["match_date"])[:10] == newer
    assert str(rows[1]["match_date"])[:10] == older
    # snapshot_kind is surfaced.
    assert rows[0]["snapshot_kind"] in {"pre_match", "retroactive"}


def test_count_pending_excludes_resolved(engine, stub_predict):
    future = (datetime.utcnow() + timedelta(days=10)).date().isoformat()
    past = (datetime.utcnow() - timedelta(days=2)).date().isoformat()
    _seed_fixture(engine, match_date=future, home_team="A", away_team="B")
    _seed_fixture(
        engine,
        match_date=past,
        home_team="C",
        away_team="D",
        home_goals=1,
        away_goals=0,
        status="completed",
    )

    wc_prediction_store.snapshot_wc_predictions(engine=engine)
    assert wc_prediction_store.count_pending_wc_predictions(engine=engine) == 2

    wc_prediction_store.backfill_completed_wc_predictions(engine=engine)
    assert wc_prediction_store.count_pending_wc_predictions(engine=engine) == 1

"""
Tests for WC2026 FastAPI routes (`/groups/standings`, `/predictions/group/{name}`,
`/unlocks`, Paystack stubs).

Uses an in-memory SQLite engine in place of PostgreSQL — SQL kept compatible
with both dialects (no PG-only features in the queries the routes execute).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


def _create_test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL DEFAULT '',
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS group_standings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT NOT NULL,
        team TEXT NOT NULL,
        played INTEGER NOT NULL DEFAULT 0,
        won INTEGER NOT NULL DEFAULT 0,
        drawn INTEGER NOT NULL DEFAULT 0,
        lost INTEGER NOT NULL DEFAULT 0,
        goals_for INTEGER NOT NULL DEFAULT 0,
        goals_against INTEGER NOT NULL DEFAULT 0,
        points INTEGER NOT NULL DEFAULT 0,
        rank INTEGER,
        fifa_rank INTEGER,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (group_name, team)
    );

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

    CREATE TABLE IF NOT EXISTS unlocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        item_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        paystack_reference TEXT,
        amount_usd NUMERIC,
        paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_id, item_key)
    );
    """
    with engine.begin() as conn:
        for stmt in schema.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
    return engine


@pytest.fixture
def app_with_stub_user():
    """
    Build a fresh FastAPI app with WC2026 routes mounted and an in-memory
    sqlite engine substituted for the real Postgres engine. Returns a tuple
    of (app, engine, fake_user_dict).
    """
    engine = _create_test_engine()

    # Seed a fake user that the get_current_user dependency will return.
    fake_user = {"user_id": 42, "email": "tester@example.com"}

    # Patch get_db_engine on every module that has already imported it
    # (the routes module captured the function reference at import time).
    import db.engine as db_engine_mod
    from app import wc2026_routes
    from core import wc_prediction_store

    original_db_engine = db_engine_mod.get_db_engine
    original_routes_engine = wc2026_routes.get_db_engine
    original_store_engine = wc_prediction_store.get_db_engine

    def _stub_engine():
        return engine

    db_engine_mod.get_db_engine = _stub_engine
    wc2026_routes.get_db_engine = _stub_engine
    wc_prediction_store.get_db_engine = _stub_engine

    try:
        app = FastAPI()

        async def stub_user() -> dict:
            return fake_user

        wc2026_routes.register_wc2026_routes(app, stub_user)

        yield app, engine, fake_user
    finally:
        db_engine_mod.get_db_engine = original_db_engine
        wc2026_routes.get_db_engine = original_routes_engine
        wc_prediction_store.get_db_engine = original_store_engine


def test_groups_standings_returns_seeded_draw_when_db_is_empty(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)

    resp = client.get("/groups/standings")
    assert resp.status_code == 200
    data = resp.json()

    assert data["tournament_started"] is False
    assert isinstance(data["source_url"], str) and data["source_url"].startswith("https://")
    assert len(data["groups"]) == 12
    group_names = [g["group"] for g in data["groups"]]
    assert group_names == [f"Group {ch}" for ch in "ABCDEFGHIJKL"]
    for group in data["groups"]:
        assert len(group["teams"]) == 4
        for team in group["teams"]:
            assert team["played"] == 0
            assert team["points"] == 0


def test_groups_standings_returns_live_data_when_present(app_with_stub_user):
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO group_standings "
                "(group_name, team, played, won, drawn, lost, goals_for, goals_against, points, rank) "
                "VALUES ('Group A', 'Mexico', 1, 1, 0, 0, 2, 0, 3, 1), "
                "('Group A', 'Korea Republic', 1, 0, 0, 1, 0, 2, 0, 2)"
            )
        )

    client = TestClient(app)
    resp = client.get("/groups/standings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tournament_started"] is True
    group_a = next(g for g in data["groups"] if g["group"] == "Group A")
    # When live data exists, only the seeded teams in the DB are returned
    # for that group (no fallback merge).
    teams = {t["team"]: t for t in group_a["teams"]}
    assert teams["Mexico"]["played"] == 1
    assert teams["Mexico"]["points"] == 3
    assert teams["Mexico"]["goal_difference"] == 2


def test_predictions_group_returns_matches_with_predictions(app_with_stub_user):
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, venue) "
                "VALUES "
                "('2026-06-11', '20:00', 'Group A', 'group', 'Mexico', 'Korea Republic', 'Estadio Azteca'), "
                "('2026-06-14', '15:00', 'Group A', 'group', 'Czechia', 'South Africa', 'BMO Field')"
            )
        )

    client = TestClient(app)
    resp = client.get("/predictions/group/Group A")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["matches"]) == 2

    first = data["matches"][0]
    assert first["home_team"] == "Mexico"
    assert first["away_team"] == "Korea Republic"
    assert first["date"] == "2026-06-11"
    pred = first["prediction"]
    assert {"home_win", "draw", "away_win", "predicted", "confidence"} <= pred.keys()
    # Mexico is favoured over Korea Republic per FIFA ranks.
    assert pred["home_win"] > pred["away_win"]
    # Scheduled fixtures must not leak goals — the wc_fixtures rows above
    # use the schema default status ('scheduled'), so the endpoint should
    # echo nulls for both score fields and 'scheduled' for status.
    assert first["status"] == "scheduled"
    assert first["home_goals"] is None
    assert first["away_goals"] is None

    winner = data["winner"]
    assert winner is not None
    assert winner["team"] in {"Mexico", "Korea Republic", "Czechia", "South Africa"}
    assert 0.0 < winner["probability"] <= 1.0


def test_predictions_group_exposes_scores_for_completed_matches(app_with_stub_user):
    """Completed matches should surface their final scoreline."""
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, "
                " venue, home_goals, away_goals, status) "
                "VALUES "
                "('2026-06-11', '20:00', 'Group A', 'group', 'Mexico', 'South Africa', "
                " 'Estadio Azteca', 2, 0, 'completed'), "
                "('2026-06-12', '15:00', 'Group A', 'group', 'Korea Republic', 'Czechia', "
                " 'BMO Field', 2, 1, 'completed')"
            )
        )

    client = TestClient(app)
    resp = client.get("/predictions/group/Group A")
    assert resp.status_code == 200
    matches = resp.json()["matches"]
    assert len(matches) == 2

    by_pair = {(m["home_team"], m["away_team"]): m for m in matches}
    mex = by_pair[("Mexico", "South Africa")]
    assert mex["status"] == "completed"
    assert mex["home_goals"] == 2
    assert mex["away_goals"] == 0

    kor = by_pair[("Korea Republic", "Czechia")]
    assert kor["status"] == "completed"
    assert kor["home_goals"] == 2
    assert kor["away_goals"] == 1


def test_wc2026_fixtures_default_returns_today_plus_window(
    app_with_stub_user, monkeypatch
):
    """Default mode: today + 6 future days, including completed-match scores."""
    from datetime import date as _date

    from app import wc2026_routes

    # Pin "today" so the test is stable regardless of when it runs.
    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return _date(2026, 6, 12)

    monkeypatch.setattr(wc2026_routes, "_date", _FixedDate)

    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, "
                " venue, home_goals, away_goals, status) "
                "VALUES "
                # Outside window (past) — must be excluded
                "('2026-06-11', '20:00', 'Group A', 'group', 'Mexico', 'South Africa', "
                " 'Estadio Azteca', 2, 0, 'completed'), "
                # Today, completed earlier in the day
                "('2026-06-12', '15:00', 'Group A', 'group', 'Korea Republic', 'Czechia', "
                " 'BMO Field', 2, 1, 'completed'), "
                # Today, still scheduled (no scores should leak)
                "('2026-06-12', '21:00', 'Group B', 'group', 'Canada', 'Switzerland', "
                " 'BMO Field', NULL, NULL, 'scheduled'), "
                # Day +6, in window
                "('2026-06-18', '20:00', 'Group C', 'group', 'Brazil', 'Morocco', "
                " 'MetLife Stadium', NULL, NULL, 'scheduled'), "
                # Day +7, just out of window
                "('2026-06-19', '15:00', 'Group D', 'group', 'USA', 'Australia', "
                " 'AT&T Stadium', NULL, NULL, 'scheduled')"
            )
        )

    client = TestClient(app)
    resp = client.get("/wc2026/fixtures")
    assert resp.status_code == 200
    body = resp.json()

    assert body["date_from"] == "2026-06-12"
    assert body["date_to"] == "2026-06-18"
    assert body["count"] == 3

    pairs = [(f["home_team"], f["away_team"]) for f in body["fixtures"]]
    assert ("Mexico", "South Africa") not in pairs  # before window
    assert ("USA", "Australia") not in pairs  # after window
    assert ("Korea Republic", "Czechia") in pairs
    assert ("Canada", "Switzerland") in pairs
    assert ("Brazil", "Morocco") in pairs

    by_pair = {(f["home_team"], f["away_team"]): f for f in body["fixtures"]}

    # Completed match exposes scores.
    kor = by_pair[("Korea Republic", "Czechia")]
    assert kor["status"] == "completed"
    assert kor["home_goals"] == 2
    assert kor["away_goals"] == 1
    assert kor["prediction"] is not None  # FIFA-Elo can predict known teams

    # Scheduled match keeps scores nulled.
    can = by_pair[("Canada", "Switzerland")]
    assert can["status"] == "scheduled"
    assert can["home_goals"] is None
    assert can["away_goals"] is None


def test_wc2026_fixtures_date_filter_returns_only_that_day(app_with_stub_user):
    """?date=YYYY-MM-DD narrows the response to a single calendar day."""
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, "
                " venue, status) "
                "VALUES "
                "('2026-06-12', '15:00', 'Group A', 'group', 'Korea Republic', 'Czechia', "
                " 'BMO Field', 'completed'), "
                "('2026-06-12', '21:00', 'Group B', 'group', 'Canada', 'Switzerland', "
                " 'BMO Field', 'scheduled'), "
                "('2026-06-13', '20:00', 'Group C', 'group', 'Brazil', 'Morocco', "
                " 'MetLife Stadium', 'scheduled')"
            )
        )

    client = TestClient(app)
    resp = client.get("/wc2026/fixtures?date=2026-06-12")
    assert resp.status_code == 200
    body = resp.json()
    assert body["date_from"] == body["date_to"] == "2026-06-12"
    assert body["count"] == 2
    assert all(f["match_date"] == "2026-06-12" for f in body["fixtures"])


def test_wc2026_fixtures_rejects_invalid_date_param(app_with_stub_user):
    client = TestClient(app_with_stub_user[0])
    # Wrong shape — pydantic regex rejects at validation layer.
    resp = client.get("/wc2026/fixtures?date=06-12-2026")
    assert resp.status_code == 422


def test_wc2026_teams_returns_48_nations(app_with_stub_user):
    """GET /wc2026/teams is public and returns the 48 nations alphabetically."""
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/teams")
    assert resp.status_code == 200
    body = resp.json()
    teams = body["teams"]
    assert len(teams) == 48
    # Sorted alphabetically — "Algeria" first, "Uzbekistan" last when sorted.
    assert teams == sorted(teams)
    # Spot-check a handful that must be present from db.seed_wc2026.GROUPS.
    for nation in ("Argentina", "Brazil", "England", "South Africa", "Mexico"):
        assert nation in teams
    # Ensure no PSL clubs slipped in.
    for psl_club in ("Kaizer Chiefs", "Orlando Pirates", "Mamelodi Sundowns"):
        assert psl_club not in teams


def test_wc2026_user_predictions_empty_for_new_user(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/predictions")
    assert resp.status_code == 200
    assert resp.json() == {"predictions": []}


def test_wc2026_upsert_group_predictions_persists_and_returns(app_with_stub_user):
    app, engine, _user = app_with_stub_user
    # Seed 3 scheduled fixtures in Group A.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, "
                " venue, status) VALUES "
                "('2026-06-15', '20:00', 'Group A', 'group', 'Mexico', 'Korea Republic', "
                " 'Estadio Azteca', 'scheduled'), "
                "('2026-06-18', '15:00', 'Group A', 'group', 'Czechia', 'South Africa', "
                " 'BMO Field', 'scheduled'), "
                "('2026-06-22', '12:00', 'Group A', 'group', 'Mexico', 'Czechia', "
                " 'Estadio Azteca', 'scheduled')"
            )
        )
        fixture_ids = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT id FROM wc_fixtures WHERE group_name = 'Group A' "
                    "ORDER BY match_date"
                )
            ).fetchall()
        ]

    client = TestClient(app)
    resp = client.put(
        "/wc2026/predictions/group/Group A",
        json={
            "picks": [
                {"fixture_id": fixture_ids[0], "predicted_outcome": "Home"},
                {"fixture_id": fixture_ids[1], "predicted_outcome": "Draw"},
                {"fixture_id": fixture_ids[2], "predicted_outcome": "Away"},
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["predictions"]) == 3
    by_fix = {p["fixture_id"]: p for p in body["predictions"]}
    assert by_fix[fixture_ids[0]]["predicted_outcome"] == "Home"
    assert by_fix[fixture_ids[1]]["predicted_outcome"] == "Draw"
    assert by_fix[fixture_ids[2]]["predicted_outcome"] == "Away"
    # All three are scheduled → none locked yet.
    assert all(p["locked"] is False for p in body["predictions"])

    # Edit one prediction — should overwrite, not duplicate.
    resp2 = client.put(
        "/wc2026/predictions/group/Group A",
        json={
            "picks": [
                {"fixture_id": fixture_ids[0], "predicted_outcome": "Away"},
            ]
        },
    )
    assert resp2.status_code == 200
    by_fix2 = {p["fixture_id"]: p for p in resp2.json()["predictions"]}
    assert by_fix2[fixture_ids[0]]["predicted_outcome"] == "Away"
    # The other two from the first call should still be there (we only
    # edited one fixture, not the whole group).
    assert by_fix2[fixture_ids[1]]["predicted_outcome"] == "Draw"
    assert by_fix2[fixture_ids[2]]["predicted_outcome"] == "Away"


def test_wc2026_upsert_rejects_fixture_outside_group(app_with_stub_user):
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, "
                " venue, status) VALUES "
                "('2026-06-15', '20:00', 'Group A', 'group', 'Mexico', 'Korea Republic', "
                " 'Estadio Azteca', 'scheduled'), "
                "('2026-06-15', '20:00', 'Group B', 'group', 'Canada', 'Switzerland', "
                " 'BMO Field', 'scheduled')"
            )
        )
        group_b_id = conn.execute(
            text("SELECT id FROM wc_fixtures WHERE group_name = 'Group B'")
        ).scalar()

    client = TestClient(app)
    # Submitting a Group B fixture under the Group A URL must fail.
    resp = client.put(
        "/wc2026/predictions/group/Group A",
        json={"picks": [{"fixture_id": group_b_id, "predicted_outcome": "Home"}]},
    )
    assert resp.status_code == 400
    assert "not part of Group A" in resp.json()["detail"]


def test_wc2026_upsert_rejects_kicked_off_fixture(app_with_stub_user):
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, "
                " venue, status) VALUES "
                "('2026-06-12', '15:00', 'Group A', 'group', 'Korea Republic', 'Czechia', "
                " 'BMO Field', 'completed'), "
                "('2026-06-15', '20:00', 'Group A', 'group', 'Mexico', 'South Africa', "
                " 'Estadio Azteca', 'scheduled')"
            )
        )
        rows = conn.execute(
            text("SELECT id, status FROM wc_fixtures WHERE group_name='Group A' ORDER BY id")
        ).fetchall()
    completed_id = next(r[0] for r in rows if r[1] == "completed")

    client = TestClient(app)
    resp = client.put(
        "/wc2026/predictions/group/Group A",
        json={"picks": [{"fixture_id": completed_id, "predicted_outcome": "Home"}]},
    )
    assert resp.status_code == 400
    assert "locked" in resp.json()["detail"].lower()


def test_wc2026_upsert_404s_for_empty_group(app_with_stub_user):
    """No fixtures in the requested group → 404, not a silent no-op."""
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.put(
        "/wc2026/predictions/group/Group Z",
        json={"picks": [{"fixture_id": 9999, "predicted_outcome": "Home"}]},
    )
    assert resp.status_code == 404


def test_wc2026_get_predictions_marks_kicked_off_as_locked(app_with_stub_user):
    """A user's prediction surfaces `locked: true` once the match starts."""
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage, home_team, away_team, "
                " venue, status, home_goals, away_goals) VALUES "
                "('2026-06-12', '15:00', 'Group A', 'group', 'Korea Republic', 'Czechia', "
                " 'BMO Field', 'completed', 2, 1)"
            )
        )
        fixture_id = conn.execute(
            text("SELECT id FROM wc_fixtures WHERE home_team='Korea Republic'")
        ).scalar()
        # Bypass the API guard and insert a stored pick directly, simulating
        # a prediction made before kickoff.
        conn.execute(
            text(
                "INSERT INTO wc_user_predictions (user_id, fixture_id, predicted_outcome) "
                "VALUES (:uid, :fid, 'Home')"
            ),
            {"uid": 42, "fid": fixture_id},
        )

    client = TestClient(app)
    resp = client.get("/wc2026/predictions")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["predictions"]) == 1
    p = body["predictions"][0]
    assert p["locked"] is True
    assert p["status"] == "completed"
    assert p["home_goals"] == 2
    assert p["away_goals"] == 1
    assert p["predicted_outcome"] == "Home"


def test_unlocks_returns_empty_list_for_user_with_no_unlocks(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/unlocks")
    assert resp.status_code == 200
    assert resp.json() == {"unlocks": []}


def test_unlocks_returns_user_specific_item_keys(app_with_stub_user):
    app, engine, fake_user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO unlocks (user_id, item_key, kind) VALUES "
                "(:uid, 'group_match:1', 'group_match'), "
                "(:uid, 'group_winner:Group A', 'group_winner'), "
                "(99, 'group_match:9', 'group_match')"
            ),
            {"uid": fake_user["user_id"]},
        )

    client = TestClient(app)
    resp = client.get("/unlocks")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["unlocks"]) == {"group_match:1", "group_winner:Group A"}


def test_paystack_init_returns_503_in_phase1(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.post(
        "/payments/paystack/init",
        json={
            "kind": "group_match",
            "item_key": "group_match:1",
            "amount_usd": 1.0,
            "callback_url": "https://example.com/cb",
        },
    )
    assert resp.status_code == 503


def test_paystack_verify_returns_unsuccessful_in_phase1(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/payments/paystack/verify?reference=anything")
    assert resp.status_code == 200
    assert resp.json() == {"success": False}


def test_refresh_endpoint_rejects_non_admin(app_with_stub_user, monkeypatch):
    app, _engine, _user = app_with_stub_user
    monkeypatch.delenv("WC_ADMIN_EMAILS", raising=False)
    client = TestClient(app)
    resp = client.post("/groups/standings/refresh")
    assert resp.status_code == 403


def test_refresh_endpoint_allows_admin(app_with_stub_user, monkeypatch):
    app, _engine, fake_user = app_with_stub_user
    monkeypatch.setenv("WC_ADMIN_EMAILS", fake_user["email"])

    # Patch scrape_groups so the admin call returns quickly without HTTP.
    from jobs import fifa_scraper

    monkeypatch.setattr(fifa_scraper, "scrape_groups", lambda: 0)

    client = TestClient(app)
    resp = client.post("/groups/standings/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert "message" in body and "updated_at" in body


# ---------- POST /wc2026/predict --------------------------------------------

def test_wc2026_predict_returns_valid_envelope(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)

    resp = client.post(
        "/wc2026/predict",
        json={"home_team": "Argentina", "away_team": "Saudi Arabia"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["home_team"] == "Argentina"
    assert body["away_team"] == "Saudi Arabia"
    assert set(body["probabilities"].keys()) == {"Home", "Draw", "Away"}
    # Probabilities should sum to ~1.0 (allow tiny float drift).
    total = sum(body["probabilities"].values())
    assert abs(total - 1.0) < 1e-6
    # Argentina is heavily favoured over Saudi Arabia per FIFA ranks.
    assert body["predicted_outcome"] == "Home"
    assert body["probabilities"]["Home"] > body["probabilities"]["Away"]
    assert body["confidence"] == body["probabilities"]["Home"]
    assert body["model_version"] == "wc2026_davidson_bt_v1"


def test_wc2026_predict_resolves_aliases(app_with_stub_user):
    """Frontend may submit 'South Korea' or 'Iran' — both must resolve via alias."""
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)

    resp = client.post(
        "/wc2026/predict",
        json={"home_team": "South Korea", "away_team": "Iran"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Endpoint echoes back the input (canonicalization happens in the
    # ranking lookup, not in the response envelope).
    assert body["home_team"] == "South Korea"
    assert body["away_team"] == "Iran"


def test_wc2026_predict_rejects_unknown_team(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)

    resp = client.post(
        "/wc2026/predict",
        json={"home_team": "Atlantis", "away_team": "Brazil"},
    )
    assert resp.status_code == 400
    assert "Atlantis" in resp.json()["detail"]


def test_wc2026_predict_rejects_same_team(app_with_stub_user):
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)

    resp = client.post(
        "/wc2026/predict",
        json={"home_team": "Brazil", "away_team": "Brazil"},
    )
    assert resp.status_code == 400


def test_wc2026_predict_rejects_empty_team(app_with_stub_user):
    """Pydantic min_length=1 should reject empty/whitespace input."""
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)

    resp = client.post(
        "/wc2026/predict",
        json={"home_team": "", "away_team": "Brazil"},
    )
    # Pydantic's min_length=1 -> 422 (FastAPI validation error)
    assert resp.status_code in (400, 422)


# ---------- /wc2026/model/status --------------------------------------------

def _make_stub_artifact(metadata: dict):
    """
    Build a minimal BTArtifact for the model-status tests.

    The route only reads `model_version`, `teams`, `n_matches`, and
    `metadata`, so we don't bother fitting anything — the strengths /
    draw_param are placeholders.
    """
    from core.wc2026_model import BTArtifact
    return BTArtifact(
        teams=["Argentina", "Brazil", "France"],
        strengths={"Argentina": 0.5, "Brazil": 0.3, "France": 0.1},
        n_matches_per_team={"Argentina": 100, "Brazil": 80, "France": 60},
        draw_param=-1.2,
        l2=0.5,
        n_matches=240,
        n_pairs=3,
        final_nll=123.4,
        metadata=metadata,
    )


def test_wc2026_model_status_returns_ready_when_artifact_loaded(
    app_with_stub_user, monkeypatch,
):
    """
    Happy path: artifact already has baked-in `evaluation` metadata
    (i.e. the model was retrained after this feature shipped).
    """
    from core import wc2026_prediction

    art = _make_stub_artifact(
        metadata={
            "evaluation": {
                "accuracy": 0.6789,
                "log_loss": 0.91,
                "brier": 0.18,
                "pred_draw_rate": 0.27,
                "n_matches": 240,
                "evaluated_at": "2026-06-12T12:00:00+00:00",
                "evaluation_kind": "in_sample",
            },
        }
    )
    monkeypatch.setattr(wc2026_prediction, "_BT_ARTIFACT", art)

    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/model/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "ready"
    assert body["model_version"] == art.model_version
    assert body["teams_count"] == 3
    assert body["n_matches"] == 240
    assert body["serving_with"] == art.model_version

    ev = body["evaluation"]
    assert ev is not None
    assert ev["accuracy"] == pytest.approx(0.6789)
    assert ev["log_loss"] == pytest.approx(0.91)
    assert ev["brier"] == pytest.approx(0.18)
    assert ev["pred_draw_rate"] == pytest.approx(0.27)
    assert ev["n_matches"] == 240
    assert ev["evaluation_kind"] == "in_sample"


def test_wc2026_model_status_recomputes_when_metadata_missing(
    app_with_stub_user, monkeypatch,
):
    """
    Older artifacts predate the bake-in change. The route should lazily
    recompute metrics from the H2H dataset, tag them `in_sample_recomputed`,
    and memoise the result on the artifact so the next call is O(1).
    """
    from app import wc2026_routes
    from core import wc2026_prediction

    art = _make_stub_artifact(metadata={})  # NO evaluation key
    monkeypatch.setattr(wc2026_prediction, "_BT_ARTIFACT", art)

    # Stub the H2H loader so the test doesn't depend on the real CSV.
    # The recompute path calls wc2026_evaluate(artifact, rows) — passing
    # an empty list is fine because evaluate() handles n_matches==0
    # gracefully (returns accuracy == 0.0).
    monkeypatch.setattr(
        wc2026_routes, "load_h2h_rows", lambda _path: [],
    )

    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/model/status")
    assert resp.status_code == 200
    body = resp.json()

    ev = body["evaluation"]
    assert ev is not None
    assert ev["evaluation_kind"] == "in_sample_recomputed"
    assert 0.0 <= ev["accuracy"] <= 1.0

    # Memoised on the artifact — second call must not re-invoke load_h2h_rows.
    sentinel = {"called": 0}

    def _exploding_loader(_path):
        sentinel["called"] += 1
        raise RuntimeError("should not be called when cached")

    monkeypatch.setattr(wc2026_routes, "load_h2h_rows", _exploding_loader)
    resp2 = client.get("/wc2026/model/status")
    assert resp2.status_code == 200
    assert sentinel["called"] == 0


def test_wc2026_model_status_returns_unavailable_when_no_artifact(
    app_with_stub_user, monkeypatch,
):
    """
    No artifact loaded (e.g. fresh deploy before any training run). The
    response should be HTTP 200 with status='unavailable' so the frontend
    can render an empty state — NOT a 5xx that breaks the page.
    """
    from core import wc2026_prediction

    monkeypatch.setattr(wc2026_prediction, "_BT_ARTIFACT", None)

    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/model/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "unavailable"
    assert body["model_version"] is None
    assert body["evaluation"] is None
    assert body["teams_count"] is None
    assert body["n_matches"] is None
    # serving_with should still resolve — _model_in_use() returns the
    # phase-1 fallback tag in this case.
    assert isinstance(body["serving_with"], str)
    assert body["serving_with"]


def test_wc2026_model_status_returns_null_eval_when_csv_missing(
    app_with_stub_user, monkeypatch,
):
    """
    Artifact has no `evaluation` metadata AND the H2H CSV is unavailable
    (e.g. slimmed-down container). The route should degrade to
    `evaluation: null` rather than 500ing.
    """
    from app import wc2026_routes
    from core import wc2026_prediction

    art = _make_stub_artifact(metadata={})
    monkeypatch.setattr(wc2026_prediction, "_BT_ARTIFACT", art)

    def _missing(_path):
        raise FileNotFoundError("simulated missing CSV")

    monkeypatch.setattr(wc2026_routes, "load_h2h_rows", _missing)

    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/model/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["evaluation"] is None


# ---------- /wc2026/benchmark ------------------------------------------------

def _stub_predict(monkeypatch):
    """Make wc2026_prediction.predict deterministic regardless of teams."""
    from core import wc2026_prediction as _wp

    monkeypatch.setattr(
        _wp,
        "predict",
        lambda h, a: {"Home": 0.6, "Draw": 0.25, "Away": 0.15},
    )
    monkeypatch.setattr(_wp, "_model_in_use", lambda: "stub_v1")


def _seed_resolved_pred(
    engine,
    *,
    fixture_id: int,
    predicted: str,
    actual_home: int,
    actual_away: int,
    snapshot_kind: str = "pre_match",
    confidence: float = 0.6,
):
    """
    Insert a wc_predictions row already in the resolved state. We bypass
    the snapshot helper so the test can pin both the prediction outcome
    and the snapshot_kind directly.
    """
    actual = (
        "Home" if actual_home > actual_away
        else "Away" if actual_away > actual_home
        else "Draw"
    )
    is_correct = predicted == actual
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_predictions ("
                " fixture_id, predicted_outcome, prob_home, prob_draw, prob_away,"
                " confidence, model_version, snapshot_kind, predicted_at,"
                " actual_outcome, actual_home_goals, actual_away_goals,"
                " is_correct, resolved_at"
                ") VALUES ("
                " :fid, :pred, 0.6, 0.25, 0.15,"
                " :conf, 'stub_v1', :kind, CURRENT_TIMESTAMP,"
                " :actual, :ahg, :aag, :correct, CURRENT_TIMESTAMP"
                ")"
            ),
            {
                "fid": fixture_id,
                "pred": predicted,
                "conf": confidence,
                "kind": snapshot_kind,
                "actual": actual,
                "ahg": actual_home,
                "aag": actual_away,
                "correct": 1 if is_correct else 0,
            },
        )


def test_wc2026_benchmark_empty_state_returns_zeroed_summary(
    app_with_stub_user,
):
    """No predictions, no fixtures - well-formed empty payload."""
    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/benchmark")
    assert resp.status_code == 200
    body = resp.json()

    assert body["summary"]["total_matches"] == 0
    assert body["summary"]["correct"] == 0
    assert body["summary"]["incorrect"] == 0
    assert body["summary"]["pending"] == 0
    assert body["summary"]["accuracy"] == 0.0
    assert body["summary"]["accuracy_by_kind"] == []
    assert body["summary"]["accuracy_by_confidence"] == []
    assert body["summary"]["accuracy_by_period"] == []
    assert body["matches"] == []
    assert body["message"]


def test_wc2026_benchmark_pending_count_reflects_unresolved_snapshots(
    app_with_stub_user, monkeypatch,
):
    """Snapshots without resolved_at land in `pending`, not `total_matches`."""
    _stub_predict(monkeypatch)

    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(match_date, kickoff_time, group_name, stage,"
                " home_team, away_team, status) "
                "VALUES "
                "('2026-06-30', '20:00', 'Group A', 'group',"
                " 'Mexico', 'Korea Republic', 'scheduled')"
            )
        )

    # Run snapshot to populate wc_predictions for the unscored fixture.
    from core.wc_prediction_store import snapshot_wc_predictions
    snapshot_wc_predictions(engine=engine)

    client = TestClient(app)
    resp = client.get("/wc2026/benchmark")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["pending"] == 1
    assert body["summary"]["total_matches"] == 0
    assert body["matches"] == []


def test_wc2026_benchmark_returns_resolved_matches_with_kind_split(
    app_with_stub_user,
):
    """
    Three resolved rows: two pre_match (1 correct, 1 wrong), one retroactive
    (correct). Verify summary math, kind split, and per-row payload.
    """
    app, engine, _user = app_with_stub_user
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wc_fixtures "
                "(id, match_date, kickoff_time, group_name, stage,"
                " home_team, away_team, home_goals, away_goals, status) "
                "VALUES "
                "(101, '2026-06-11', '20:00', 'Group A', 'group',"
                " 'Mexico', 'South Africa', 2, 0, 'completed'),"
                "(102, '2026-06-12', '15:00', 'Group A', 'group',"
                " 'Korea Republic', 'Czechia', 0, 1, 'completed'),"
                "(103, '2026-06-13', '12:00', 'Group B', 'group',"
                " 'Argentina', 'Saudi Arabia', 1, 0, 'completed')"
            )
        )

    # Pre-match correct: predicted Home, actual Home (Mexico won 2-0).
    _seed_resolved_pred(
        engine, fixture_id=101, predicted="Home",
        actual_home=2, actual_away=0,
        snapshot_kind="pre_match", confidence=0.7,
    )
    # Pre-match wrong: predicted Home, actual Away (Czechia won 0-1).
    _seed_resolved_pred(
        engine, fixture_id=102, predicted="Home",
        actual_home=0, actual_away=1,
        snapshot_kind="pre_match", confidence=0.45,
    )
    # Retroactive correct: predicted Home, actual Home.
    _seed_resolved_pred(
        engine, fixture_id=103, predicted="Home",
        actual_home=1, actual_away=0,
        snapshot_kind="retroactive", confidence=0.8,
    )

    client = TestClient(app)
    resp = client.get("/wc2026/benchmark")
    assert resp.status_code == 200
    body = resp.json()

    summary = body["summary"]
    assert summary["total_matches"] == 3
    assert summary["correct"] == 2
    assert summary["incorrect"] == 1
    assert summary["pending"] == 0
    assert summary["accuracy"] == pytest.approx(2 / 3)

    kinds = {k["snapshot_kind"]: k for k in summary["accuracy_by_kind"]}
    assert kinds["pre_match"]["total"] == 2
    assert kinds["pre_match"]["correct"] == 1
    assert kinds["pre_match"]["incorrect"] == 1
    assert kinds["pre_match"]["accuracy"] == pytest.approx(0.5)
    assert kinds["retroactive"]["total"] == 1
    assert kinds["retroactive"]["correct"] == 1
    assert kinds["retroactive"]["accuracy"] == pytest.approx(1.0)

    matches = body["matches"]
    assert len(matches) == 3
    # Newest first by match_date.
    assert [m["match_date"] for m in matches] == [
        "2026-06-13", "2026-06-12", "2026-06-11",
    ]
    for row in matches:
        assert row["snapshot_kind"] in {"pre_match", "retroactive"}
        assert row["confidence"] in {"Low", "Medium", "High"}
        assert row["predicted_outcome"] in {"Home Win", "Draw", "Away Win"}

    # Confidence buckets cover the seeded values: 0.45 -> Medium, 0.7 / 0.8 -> High.
    confs = {b["confidence"]: b for b in summary["accuracy_by_confidence"]}
    assert "High" in confs
    assert "Medium" in confs
    assert confs["High"]["count"] == 2
    assert confs["Medium"]["count"] == 1


def test_wc2026_benchmark_holdout_block_carries_artifact_metrics(
    app_with_stub_user, monkeypatch,
):
    """
    With a baked-in `evaluation` block on the artifact, /wc2026/benchmark
    surfaces it under `holdout` so the FE can show the model's training
    metrics alongside live results.
    """
    from core import wc2026_prediction

    art = _make_stub_artifact(
        metadata={
            "evaluation": {
                "accuracy": 0.55,
                "log_loss": 0.92,
                "brier": 0.20,
                "pred_draw_rate": 0.27,
                "n_matches": 240,
                "evaluated_at": "2026-06-01T00:00:00Z",
                "evaluation_kind": "in_sample",
            }
        }
    )
    monkeypatch.setattr(wc2026_prediction, "_BT_ARTIFACT", art)

    app, _engine, _user = app_with_stub_user
    client = TestClient(app)
    resp = client.get("/wc2026/benchmark")
    assert resp.status_code == 200
    body = resp.json()

    assert body["holdout"] is not None
    assert body["holdout"]["accuracy"] == pytest.approx(0.55)
    assert body["holdout"]["evaluation_kind"] == "in_sample"
    assert body["holdout"]["n_matches"] == 240


def test_wc2026_benchmark_requires_auth():
    """
    Unauthenticated callers get 401 - matches the PSL /benchmark contract.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    import db.engine as db_engine_mod
    from app import wc2026_routes
    from core import wc_prediction_store

    monkeypatch_engine = wc2026_routes.get_db_engine
    monkeypatch_db = db_engine_mod.get_db_engine
    monkeypatch_store = wc_prediction_store.get_db_engine
    db_engine_mod.get_db_engine = lambda: engine
    wc2026_routes.get_db_engine = lambda: engine
    wc_prediction_store.get_db_engine = lambda: engine

    try:
        from fastapi import FastAPI, HTTPException
        app = FastAPI()

        async def reject_user():
            raise HTTPException(status_code=401, detail="unauth")

        wc2026_routes.register_wc2026_routes(app, reject_user)
        client = TestClient(app)
        resp = client.get("/wc2026/benchmark")
        assert resp.status_code == 401
    finally:
        db_engine_mod.get_db_engine = monkeypatch_db
        wc2026_routes.get_db_engine = monkeypatch_engine
        wc_prediction_store.get_db_engine = monkeypatch_store


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

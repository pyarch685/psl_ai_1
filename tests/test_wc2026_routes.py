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

    original_db_engine = db_engine_mod.get_db_engine
    original_routes_engine = wc2026_routes.get_db_engine

    def _stub_engine():
        return engine

    db_engine_mod.get_db_engine = _stub_engine
    wc2026_routes.get_db_engine = _stub_engine

    try:
        app = FastAPI()

        async def stub_user() -> dict:
            return fake_user

        wc2026_routes.register_wc2026_routes(app, stub_user)

        yield app, engine, fake_user
    finally:
        db_engine_mod.get_db_engine = original_db_engine
        wc2026_routes.get_db_engine = original_routes_engine


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

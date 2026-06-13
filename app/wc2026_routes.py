"""
FastAPI routes for the WC2026 (FIFA World Cup 2026) surface.

Additive — these endpoints live alongside the existing PSL routes and do not
change any PSL behaviour. They are mounted at the bottom of `app/api.py` via
`register_wc2026_routes(app)`.

Phase 1 contract (matches `src/wc2026/lib/api.ts`):

- GET  /groups/standings              public  (live standings + draw fallback)
- POST /groups/standings/refresh      auth    (admin allowlist; triggers scraper)
- GET  /predictions/group/{name}      auth    (FIFA-Elo predictions per group)
- GET  /wc2026/fixtures               public  (tournament-wide fixtures by day)
- GET  /wc2026/teams                  public  (48 nations in the WC2026 draw)
- GET  /wc2026/model/status           public  (live BT artifact metrics)
- GET  /wc2026/benchmark              auth    (model predictions vs real results)
- GET  /wc2026/predictions            auth    (current user's saved picks)
- PUT  /wc2026/predictions/group/{g}  auth    (bulk upsert per group)
- POST /payments/paystack/init        auth    (Phase 1 stub — 503)
- GET  /payments/paystack/verify      auth    (Phase 1 stub — {success: false})
- GET  /unlocks                       auth    (Phase 1 stub — {unlocks: []})
"""
from __future__ import annotations

import logging
import os
from datetime import date as _date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from core import wc2026_prediction
from core.fifa_rankings import has_rank
from core.wc2026_dataset import DEFAULT_DATA_PATH, load_h2h_rows
from core.wc2026_model import BTArtifact, evaluate as wc2026_evaluate
from db.engine import get_db_engine
from db.seed_wc2026 import GROUPS as STATIC_GROUPS

logger = logging.getLogger(__name__)


# FIFA's public source page for WC2026 group standings (informational only).
GROUPS_SOURCE_URL = (
    "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/groups"
)


# ---------- Schemas ----------------------------------------------------------

class GroupStandingTeam(BaseModel):
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    rank: Optional[int] = None


class GroupStanding(BaseModel):
    group: str
    teams: List[GroupStandingTeam]


class GroupStandingsResponse(BaseModel):
    groups: List[GroupStanding]
    updated_at: str
    source_url: str
    tournament_started: bool


class GroupStandingsRefreshResponse(BaseModel):
    message: str
    updated_at: str


class GroupMatchPrediction(BaseModel):
    id: int
    home_team: str
    away_team: str
    date: str
    time: Optional[str] = None
    prediction: Optional[Dict[str, Any]] = None
    # Live/result fields, populated for matches the FIFA scraper has
    # observed kick off. `status` mirrors `wc_fixtures.status`
    # (scheduled / live / completed) so the frontend can switch between
    # a pre-match prediction view and a results view. `home_goals` /
    # `away_goals` are only meaningful for live / completed matches.
    status: Optional[str] = None
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None


class GroupWinnerPrediction(BaseModel):
    team: str
    probability: float


class GroupPredictionsResponse(BaseModel):
    matches: List[GroupMatchPrediction]
    winner: Optional[GroupWinnerPrediction] = None


class TeamsResponse(BaseModel):
    teams: List[str]


class Wc2026ModelEvaluation(BaseModel):
    """Headline accuracy metrics for the WC2026 BT artifact.

    `evaluation_kind` is `"in_sample"` when the metrics were baked in at
    training time (the common case after a fresh retrain) and
    `"in_sample_recomputed"` when the API layer had to re-derive them at
    runtime because the loaded artifact predates this feature. Both are
    in-sample — a chronological holdout split is a tracked follow-up.
    """

    accuracy: float
    log_loss: float
    brier: float
    pred_draw_rate: float
    n_matches: int
    evaluated_at: str
    evaluation_kind: str  # 'in_sample' | 'in_sample_recomputed'


class Wc2026ModelStatusResponse(BaseModel):
    status: str  # 'ready' | 'unavailable'
    model_version: Optional[str] = None
    serving_with: str  # see core.wc2026_prediction._model_in_use()
    teams_count: Optional[int] = None
    n_matches: Optional[int] = None
    evaluation: Optional[Wc2026ModelEvaluation] = None


class UserPrediction(BaseModel):
    """A single saved user prediction joined with its fixture."""

    fixture_id: int
    group_name: Optional[str] = None
    match_date: str
    kickoff_time: Optional[str] = None
    home_team: str
    away_team: str
    status: str
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    predicted_outcome: str  # 'Home' / 'Draw' / 'Away'
    locked: bool  # True once the match has kicked off (uneditable)
    updated_at: str


class UserPredictionsResponse(BaseModel):
    predictions: List[UserPrediction]


class GroupPredictionSubmission(BaseModel):
    fixture_id: int
    predicted_outcome: str = Field(..., pattern="^(Home|Draw|Away)$")


class GroupPredictionsSubmitRequest(BaseModel):
    picks: List[GroupPredictionSubmission]


class WcFixture(BaseModel):
    """A single WC2026 fixture row enriched with a model prediction."""

    id: int
    match_date: str
    kickoff_time: Optional[str] = None
    group_name: Optional[str] = None
    stage: str
    home_team: str
    away_team: str
    venue: Optional[str] = None
    status: str
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    prediction: Optional[Dict[str, Any]] = None


class WcFixturesResponse(BaseModel):
    fixtures: List[WcFixture]
    date_from: str
    date_to: str
    count: int


class PaystackInitRequest(BaseModel):
    kind: str
    item_key: str
    amount_usd: float
    callback_url: Optional[str] = None


class Wc2026BenchmarkBucketAccuracy(BaseModel):
    """Accuracy for one confidence bucket (Low / Medium / High)."""

    confidence: str
    accuracy: float
    count: int


class Wc2026BenchmarkPeriodAccuracy(BaseModel):
    """Accuracy for one calendar period (YYYY-MM key)."""

    period: str
    accuracy: float
    correct: int
    total: int


class Wc2026BenchmarkKindAccuracy(BaseModel):
    """
    Accuracy for one snapshot_kind subset (`pre_match` or `retroactive`).

    The pre-match subset is the trustworthy benchmark; the retroactive
    subset is only honest because the WC2026 BT artifact is offline-trained.
    """

    snapshot_kind: str  # 'pre_match' | 'retroactive'
    total: int
    correct: int
    incorrect: int
    accuracy: float


class Wc2026BenchmarkSummary(BaseModel):
    total_matches: int
    correct: int
    incorrect: int
    pending: int
    accuracy: float
    accuracy_by_kind: List[Wc2026BenchmarkKindAccuracy]
    accuracy_by_confidence: List[Wc2026BenchmarkBucketAccuracy]
    accuracy_by_period: List[Wc2026BenchmarkPeriodAccuracy]


class Wc2026BenchmarkMatch(BaseModel):
    """A single resolved row for the benchmark match-by-match table."""

    id: int
    fixture_id: int
    match_date: str
    kickoff_time: Optional[str] = None
    group_name: Optional[str] = None
    stage: str
    home_team: str
    away_team: str
    predicted_outcome: str  # 'Home Win' | 'Draw' | 'Away Win'
    actual_outcome: Optional[str] = None
    actual_score: Optional[str] = None
    correct: Optional[bool] = None
    confidence: str  # 'Low' | 'Medium' | 'High'
    snapshot_kind: str  # 'pre_match' | 'retroactive'


class Wc2026BenchmarkResponse(BaseModel):
    summary: Wc2026BenchmarkSummary
    matches: List[Wc2026BenchmarkMatch]
    holdout: Optional[Wc2026ModelEvaluation] = None
    message: Optional[str] = None


class WcPredictionRequest(BaseModel):
    """Request body for POST /wc2026/predict."""

    home_team: str = Field(..., min_length=1, max_length=80)
    away_team: str = Field(..., min_length=1, max_length=80)


class WcPredictionResponse(BaseModel):
    """
    Response envelope for POST /wc2026/predict.

    Shape mirrors `/predict` so the existing frontend transformer in
    `src/wc2026/lib/api.ts` can consume both. `model_version` is added so
    Phase 2 ML upgrades are visible client-side.
    """

    home_team: str
    away_team: str
    probabilities: Dict[str, float]
    predicted_outcome: str
    confidence: float
    model_version: str


# ---------- Helpers ----------------------------------------------------------

def _admin_emails() -> set[str]:
    """
    Parse the comma-separated WC_ADMIN_EMAILS env var into a normalized set.
    """
    raw = os.getenv("WC_ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _require_admin(current_user: Dict[str, Any]) -> None:
    """
    Authorize the request as a WC2026 admin via env allowlist.

    Raises HTTPException(403) when the caller's email is not in
    WC_ADMIN_EMAILS.
    """
    email = (current_user.get("email") or "").strip().lower()
    allowed = _admin_emails()
    if not allowed:
        # Fail closed when no allowlist is configured.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin allowlist not configured (WC_ADMIN_EMAILS).",
        )
    if email not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


def _confidence_label(p: float) -> str:
    if p >= 0.6:
        return "High"
    if p >= 0.4:
        return "Medium"
    return "Low"


def _outcome_display(label: str) -> str:
    mapping = {"Home": "Home Win", "Draw": "Draw", "Away": "Away Win"}
    return mapping.get(label, label)


def _format_iso(dt: Any) -> str:
    """
    Render a `updated_at` value (datetime, ISO string, or None) as an ISO-8601
    string with a UTC suffix when no timezone info is present.
    """
    if dt is None:
        return datetime.utcnow().isoformat() + "Z"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.isoformat() + "Z"
        return dt.isoformat()
    # SQLite returns CURRENT_TIMESTAMP as a string; pass through and add Z
    # when the suffix is missing so the contract stays "ISO with TZ".
    text_val = str(dt)
    if text_val.endswith("Z") or "+" in text_val:
        return text_val
    return text_val + "Z"


# ---------- Endpoint implementations ----------------------------------------

def _load_standings_rows() -> tuple[List[Dict[str, Any]], Optional[datetime]]:
    """
    Load group_standings rows. Returns (rows, most_recent_updated_at).
    """
    engine = get_db_engine()
    rows: List[Dict[str, Any]] = []
    latest: Optional[datetime] = None
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT group_name, team, played, won, drawn, lost,
                       goals_for, goals_against, points, rank, updated_at
                FROM group_standings
                ORDER BY group_name, rank NULLS LAST, points DESC,
                         (goals_for - goals_against) DESC, team
                """
            )
        )
        for row in result.mappings():
            rows.append(dict(row))
            ts = row.get("updated_at")
            if ts is not None and (latest is None or ts > latest):
                latest = ts
    return rows, latest


def _build_groups_response() -> GroupStandingsResponse:
    rows, latest = _load_standings_rows()

    # Bucket by group.
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_group.setdefault(r["group_name"], []).append(r)

    # If the DB has no rows yet, fall back to the static draw so the frontend
    # still renders 12 groups × 4 teams with zeroed stats.
    if not by_group:
        for group_name, teams in STATIC_GROUPS.items():
            by_group[group_name] = [
                {
                    "group_name": group_name,
                    "team": t,
                    "played": 0,
                    "won": 0,
                    "drawn": 0,
                    "lost": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "points": 0,
                    "rank": None,
                }
                for t in teams
            ]

    # The tournament is considered started once any team has played a match.
    tournament_started = any(
        (r.get("played") or 0) > 0 for group in by_group.values() for r in group
    )

    groups: List[GroupStanding] = []
    for group_name in sorted(by_group.keys()):
        teams_payload = [
            GroupStandingTeam(
                team=r["team"],
                played=int(r.get("played") or 0),
                won=int(r.get("won") or 0),
                drawn=int(r.get("drawn") or 0),
                lost=int(r.get("lost") or 0),
                goals_for=int(r.get("goals_for") or 0),
                goals_against=int(r.get("goals_against") or 0),
                goal_difference=int((r.get("goals_for") or 0) - (r.get("goals_against") or 0)),
                points=int(r.get("points") or 0),
                rank=int(r["rank"]) if r.get("rank") is not None else None,
            )
            for r in by_group[group_name]
        ]
        groups.append(GroupStanding(group=group_name, teams=teams_payload))

    return GroupStandingsResponse(
        groups=groups,
        updated_at=_format_iso(latest),
        source_url=GROUPS_SOURCE_URL,
        tournament_started=tournament_started,
    )


def _load_fixtures_window(date_from: _date, date_to: _date) -> List[Dict[str, Any]]:
    """
    Load wc_fixtures rows whose match_date falls in the inclusive
    [date_from, date_to] window, ordered chronologically and then by id so
    multi-match days have a stable order.
    """
    engine = get_db_engine()
    out: List[Dict[str, Any]] = []
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT id, match_date, kickoff_time, group_name, stage,
                       home_team, away_team, venue, status,
                       home_goals, away_goals
                FROM wc_fixtures
                WHERE match_date >= :date_from AND match_date <= :date_to
                ORDER BY match_date, kickoff_time NULLS LAST, id
                """
            ),
            {"date_from": date_from, "date_to": date_to},
        )
        for row in result.mappings():
            out.append(dict(row))
    return out


def _build_fixtures_response(
    date_from: _date,
    date_to: _date,
) -> WcFixturesResponse:
    """
    Build the /wc2026/fixtures payload for the given inclusive date window.
    Predictions are attached only for teams the FIFA-Elo model recognizes
    so unrecognized knockout-placeholder slots (e.g. "Winner Group A")
    silently fall back to `prediction=None` instead of HTTP-500-ing.
    """
    rows = _load_fixtures_window(date_from, date_to)

    fixtures: List[WcFixture] = []
    for r in rows:
        status_raw = r.get("status") or "scheduled"
        # Only expose scores once the match is live or completed — see
        # the matching guard in _build_group_predictions.
        home_goals = r.get("home_goals") if status_raw in ("completed", "live") else None
        away_goals = r.get("away_goals") if status_raw in ("completed", "live") else None

        prediction: Optional[Dict[str, Any]] = None
        home_team = r["home_team"]
        away_team = r["away_team"]
        if has_rank(home_team) and has_rank(away_team):
            try:
                probs = wc2026_prediction.predict(home_team, away_team)
                outcome = wc2026_prediction.outcome_from_probs(probs)
                prediction = {
                    "home_win": probs["Home"],
                    "draw": probs["Draw"],
                    "away_win": probs["Away"],
                    "predicted": _outcome_display(outcome),
                    "confidence": _confidence_label(probs[outcome]),
                }
            except Exception as exc:
                # Predictions are non-essential here — log and serve the
                # fixture without a model overlay rather than failing the
                # whole tab.
                logger.warning(
                    f"[wc2026] prediction failed for {home_team} vs {away_team}: {exc}"
                )

        fixtures.append(
            WcFixture(
                id=int(r["id"]),
                match_date=str(r["match_date"])[:10],
                kickoff_time=r.get("kickoff_time") or None,
                group_name=r.get("group_name") or None,
                stage=r.get("stage") or "group",
                home_team=home_team,
                away_team=away_team,
                venue=r.get("venue") or None,
                status=status_raw,
                home_goals=int(home_goals) if home_goals is not None else None,
                away_goals=int(away_goals) if away_goals is not None else None,
                prediction=prediction,
            )
        )

    return WcFixturesResponse(
        fixtures=fixtures,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        count=len(fixtures),
    )


# ---------- User predictions schema bootstrap --------------------------------
#
# `wc_user_predictions` is created by migration 004 in production. Calling
# this helper at route-registration time guarantees the table exists even
# on environments (local dev, fresh test DBs, brand-new Railway deploys
# before the migration is run) that haven't applied it yet. Uses
# CREATE TABLE IF NOT EXISTS so it's a true no-op when the table is
# already present.

_USER_PREDICTIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wc_user_predictions (
    id {serial} PRIMARY KEY,
    user_id INTEGER NOT NULL,
    fixture_id INTEGER NOT NULL,
    predicted_outcome TEXT NOT NULL
        CHECK (predicted_outcome IN ('Home','Draw','Away')),
    created_at TIMESTAMP NOT NULL DEFAULT {now}(),
    updated_at TIMESTAMP NOT NULL DEFAULT {now}(),
    UNIQUE (user_id, fixture_id)
);
"""


# Mirrors db/migrations/005_add_wc_predictions.py. Kept here so a fresh
# Railway deploy can serve /wc2026/benchmark before the migration runs.
_WC_PREDICTIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wc_predictions (
    id {serial} PRIMARY KEY,
    fixture_id INTEGER NOT NULL UNIQUE,
    predicted_outcome TEXT NOT NULL
        CHECK (predicted_outcome IN ('Home','Draw','Away')),
    prob_home REAL NOT NULL,
    prob_draw REAL NOT NULL,
    prob_away REAL NOT NULL,
    confidence REAL NOT NULL,
    model_version TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL
        CHECK (snapshot_kind IN ('pre_match','retroactive')),
    predicted_at TIMESTAMP NOT NULL DEFAULT {now}(),
    actual_outcome TEXT
        CHECK (actual_outcome IN ('Home','Draw','Away')),
    actual_home_goals INTEGER,
    actual_away_goals INTEGER,
    is_correct BOOLEAN,
    resolved_at TIMESTAMP
);
"""


def _ensure_user_predictions_schema() -> None:
    """
    Create wc_user_predictions if it doesn't exist. Idempotent and safe to
    invoke on every app startup.
    """
    engine = get_db_engine()
    dialect = engine.dialect.name  # 'postgresql' / 'sqlite' in tests
    serial = "SERIAL" if dialect != "sqlite" else "INTEGER"
    now_fn = "NOW" if dialect != "sqlite" else "CURRENT_TIMESTAMP"
    sql = _USER_PREDICTIONS_SCHEMA_SQL.format(serial=serial, now=now_fn)
    # SQLite's `CURRENT_TIMESTAMP` is a reserved keyword, not a callable,
    # so strip the parentheses on that dialect to keep the DDL portable.
    if dialect == "sqlite":
        sql = sql.replace("CURRENT_TIMESTAMP()", "CURRENT_TIMESTAMP")
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception as exc:
        logger.warning(
            f"[wc2026] Could not ensure wc_user_predictions schema: {exc}"
        )


def _ensure_wc_predictions_schema() -> None:
    """
    Create wc_predictions if it doesn't exist. Idempotent. Mirrors the DDL
    in db/migrations/005_add_wc_predictions.py so /wc2026/benchmark works
    on environments where migration 005 hasn't been run yet.
    """
    engine = get_db_engine()
    dialect = engine.dialect.name
    serial = "SERIAL" if dialect != "sqlite" else "INTEGER"
    now_fn = "NOW" if dialect != "sqlite" else "CURRENT_TIMESTAMP"
    sql = _WC_PREDICTIONS_SCHEMA_SQL.format(serial=serial, now=now_fn)
    if dialect == "sqlite":
        sql = sql.replace("CURRENT_TIMESTAMP()", "CURRENT_TIMESTAMP")
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception as exc:
        logger.warning(
            f"[wc2026] Could not ensure wc_predictions schema: {exc}"
        )


def _fixture_has_kicked_off(fixture: Dict[str, Any]) -> bool:
    """
    A fixture is considered locked (no further predictions) as soon as it's
    live or completed. We deliberately don't compare wall-clock kickoff
    times against `now()` — the source of truth is the scraper's `status`
    column, so users get a few extra minutes of grace if FIFA hasn't yet
    flipped the row to `live`.
    """
    return (fixture.get("status") or "scheduled") in ("live", "completed")


def _load_user_predictions(user_id: int) -> List[Dict[str, Any]]:
    """
    Return the user's saved predictions joined with the fixture they
    reference, ordered chronologically.
    """
    engine = get_db_engine()
    out: List[Dict[str, Any]] = []
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT
                    p.fixture_id, p.predicted_outcome, p.updated_at,
                    f.group_name, f.match_date, f.kickoff_time,
                    f.home_team, f.away_team, f.status,
                    f.home_goals, f.away_goals
                FROM wc_user_predictions p
                JOIN wc_fixtures f ON f.id = p.fixture_id
                WHERE p.user_id = :uid
                ORDER BY f.match_date, f.kickoff_time NULLS LAST, f.id
                """
            ),
            {"uid": user_id},
        )
        for row in result.mappings():
            out.append(dict(row))
    return out


def _load_group_fixtures(group_name: str) -> List[Dict[str, Any]]:
    """
    Load WC fixtures for a given group ordered by date.
    """
    engine = get_db_engine()
    out: List[Dict[str, Any]] = []
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT id, match_date, kickoff_time, home_team, away_team,
                       venue, status, home_goals, away_goals
                FROM wc_fixtures
                WHERE group_name = :group_name
                ORDER BY match_date, id
                """
            ),
            {"group_name": group_name},
        )
        for row in result.mappings():
            out.append(dict(row))
    return out


def _build_group_predictions(group_name: str) -> GroupPredictionsResponse:
    fixtures = _load_group_fixtures(group_name)

    matches: List[GroupMatchPrediction] = []
    for fx in fixtures:
        probs = wc2026_prediction.predict(fx["home_team"], fx["away_team"])
        outcome = wc2026_prediction.outcome_from_probs(probs)
        confidence = probs[outcome]
        status_raw = fx.get("status")
        # Only expose scores once the match is live or completed —
        # `wc_fixtures.home_goals` is nullable for scheduled fixtures and
        # we'd rather return null than 0 so the frontend can distinguish
        # "0-0 final" from "not yet kicked off".
        home_goals = fx.get("home_goals") if status_raw in ("completed", "live") else None
        away_goals = fx.get("away_goals") if status_raw in ("completed", "live") else None
        matches.append(
            GroupMatchPrediction(
                id=int(fx["id"]),
                home_team=fx["home_team"],
                away_team=fx["away_team"],
                date=str(fx["match_date"])[:10],
                time=fx.get("kickoff_time") or None,
                prediction={
                    "home_win": probs["Home"],
                    "draw": probs["Draw"],
                    "away_win": probs["Away"],
                    "predicted": _outcome_display(outcome),
                    "confidence": _confidence_label(confidence),
                },
                status=status_raw or None,
                home_goals=int(home_goals) if home_goals is not None else None,
                away_goals=int(away_goals) if away_goals is not None else None,
            )
        )

    # Winner forecast — uses the seeded/standings team list for the group.
    teams = STATIC_GROUPS.get(group_name) or []
    if not teams:
        # Try to pull team list from group_standings as a fallback.
        engine = get_db_engine()
        with engine.connect() as conn:
            res = conn.execute(
                text("SELECT team FROM group_standings WHERE group_name = :g"),
                {"g": group_name},
            )
            teams = [r[0] for r in res.fetchall()]

    winner: Optional[GroupWinnerPrediction] = None
    if teams:
        probs = wc2026_prediction.group_winner_probability(teams)
        if probs:
            team, prob = max(probs.items(), key=lambda x: x[1])
            winner = GroupWinnerPrediction(team=team, probability=prob)

    return GroupPredictionsResponse(matches=matches, winner=winner)


# ---------- Model status helpers --------------------------------------------

def _get_evaluation_metrics(
    artifact: BTArtifact,
) -> Optional[Dict[str, Any]]:
    """
    Resolve in-sample evaluation metrics for the loaded WC2026 artifact.

    Fast path: a recently-trained artifact already has metrics baked into
    `metadata["evaluation"]` (see core.wc2026_train), so we just hand them
    back unmodified.

    Slow path (one-shot per process lifetime): older artifacts saved before
    that change have no `evaluation` key. We recompute from the on-disk H2H
    CSV via `wc2026_evaluate` and memoise the result on `artifact.metadata`
    so subsequent calls are O(1). The kind is tagged
    `in_sample_recomputed` so the UI / future debugging can tell it apart
    from a bake-in.

    Returns None only if the metadata is missing AND the CSV cannot be
    loaded (e.g. the file is absent in a slimmed-down container build) —
    callers should serialise `evaluation: null` in that case.
    """
    existing = artifact.metadata.get("evaluation")
    if isinstance(existing, dict) and "accuracy" in existing:
        return existing

    try:
        rows = load_h2h_rows(DEFAULT_DATA_PATH)
        metrics = wc2026_evaluate(artifact, rows)
    except FileNotFoundError:
        logger.warning(
            "[wc2026] H2H dataset missing at %s — cannot backfill metrics.",
            DEFAULT_DATA_PATH,
        )
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "[wc2026] Failed to lazily recompute model metrics: %s", exc,
        )
        return None

    recomputed = {
        "accuracy": float(metrics["accuracy"]),
        "log_loss": float(metrics["log_loss"]),
        "brier": float(metrics["brier"]),
        "pred_draw_rate": float(metrics["pred_draw_rate"]),
        "n_matches": int(metrics["n_matches"]),
        "evaluated_at": datetime.utcnow().isoformat() + "Z",
        "evaluation_kind": "in_sample_recomputed",
    }
    # Cache on the artifact so subsequent requests in this process skip
    # the recompute. We intentionally do NOT re-pickle to disk — running
    # under uvicorn we don't want a request handler to touch the model
    # file. A proper bake-in happens on the next `python -m core.wc2026_train`.
    artifact.metadata["evaluation"] = recomputed
    return recomputed


# ---------- Benchmark helpers ------------------------------------------------

def _confidence_label(conf: float) -> str:
    """Bucket a 0..1 confidence into Low / Medium / High.

    Mirrors `app.api._confidence_to_str` but inlined to avoid a
    cross-module import that would create a circular dependency
    (app.api imports from app.wc2026_routes).
    """
    if conf >= 0.6:
        return "High"
    if conf >= 0.4:
        return "Medium"
    return "Low"


def _outcome_to_display(outcome: str) -> str:
    """Map 'Home' / 'Draw' / 'Away' to the display labels the FE expects."""
    return {"Home": "Home Win", "Draw": "Draw", "Away": "Away Win"}.get(
        outcome, outcome,
    )


def _confidence_order(label: str) -> int:
    order = ("Low", "Medium", "High")
    return order.index(label) if label in order else 99


def _build_wc_benchmark_response() -> Wc2026BenchmarkResponse:
    """
    Compose the GET /wc2026/benchmark payload.

    Reads resolved wc_predictions joined with wc_fixtures, plus the
    pending-snapshot count. The model's holdout-evaluation block is
    always included (when available) so the FE can show it as a
    baseline alongside live data.
    """
    from core.wc_prediction_store import (
        count_pending_wc_predictions,
        load_resolved_wc_predictions,
    )

    rows = load_resolved_wc_predictions(limit=400)
    pending = count_pending_wc_predictions()

    matches: List[Wc2026BenchmarkMatch] = []
    correct = 0
    incorrect = 0

    # Per-kind accumulators -------------------------------------------------
    by_kind: Dict[str, Dict[str, int]] = {
        "pre_match": {"correct": 0, "incorrect": 0, "total": 0},
        "retroactive": {"correct": 0, "incorrect": 0, "total": 0},
    }

    # Per-confidence-bucket accumulators ------------------------------------
    by_conf: Dict[str, Dict[str, int]] = {}

    # Per-month accumulators ------------------------------------------------
    by_period: Dict[str, Dict[str, int]] = {}

    for row in rows:
        try:
            home_goals = int(row.get("actual_home_goals")) if row.get("actual_home_goals") is not None else None
            away_goals = int(row.get("actual_away_goals")) if row.get("actual_away_goals") is not None else None
        except (TypeError, ValueError):
            home_goals = None
            away_goals = None

        if home_goals is None or away_goals is None:
            # Defensive: load_resolved_wc_predictions filters for
            # resolved_at IS NOT NULL, but rows can theoretically still
            # be missing scores in pathological data.
            continue

        actual_score = f"{home_goals}-{away_goals}"
        # SQLite returns BOOLEAN columns as 1 / 0 ints; normalise to a real
        # bool (or None when unresolved) before counting.
        raw_is_correct = row.get("is_correct")
        is_correct: Optional[bool] = (
            None if raw_is_correct is None else bool(raw_is_correct)
        )
        if is_correct is True:
            correct += 1
        elif is_correct is False:
            incorrect += 1

        # match_date can come back as datetime.date or str depending on
        # dialect; normalize to YYYY-MM-DD for the wire.
        match_date = row.get("match_date")
        if hasattr(match_date, "strftime"):
            date_str = match_date.strftime("%Y-%m-%d")
        else:
            date_str = str(match_date)[:10] if match_date else ""

        kind = row.get("snapshot_kind") or "retroactive"
        if kind not in by_kind:
            by_kind[kind] = {"correct": 0, "incorrect": 0, "total": 0}
        if is_correct is not None:
            by_kind[kind]["total"] += 1
            if is_correct:
                by_kind[kind]["correct"] += 1
            else:
                by_kind[kind]["incorrect"] += 1

        confidence_label = _confidence_label(float(row.get("confidence") or 0.0))
        if is_correct is not None:
            bucket = by_conf.setdefault(
                confidence_label, {"correct": 0, "total": 0}
            )
            bucket["total"] += 1
            if is_correct:
                bucket["correct"] += 1

            period = date_str[:7] if len(date_str) >= 7 else "unknown"
            month = by_period.setdefault(period, {"correct": 0, "total": 0})
            month["total"] += 1
            if is_correct:
                month["correct"] += 1

        matches.append(
            Wc2026BenchmarkMatch(
                id=int(row["id"]),
                fixture_id=int(row["fixture_id"]),
                match_date=date_str,
                kickoff_time=row.get("kickoff_time") or None,
                group_name=row.get("group_name") or None,
                stage=str(row.get("stage") or "group"),
                home_team=str(row.get("home_team") or ""),
                away_team=str(row.get("away_team") or ""),
                predicted_outcome=_outcome_to_display(
                    str(row.get("predicted_outcome") or "")
                ),
                actual_outcome=(
                    _outcome_to_display(str(row["actual_outcome"]))
                    if row.get("actual_outcome")
                    else None
                ),
                actual_score=actual_score,
                correct=is_correct,
                confidence=confidence_label,
                snapshot_kind=kind,
            )
        )

    total = correct + incorrect
    accuracy = (correct / total) if total > 0 else 0.0

    accuracy_by_kind = [
        Wc2026BenchmarkKindAccuracy(
            snapshot_kind=kind,
            total=data["total"],
            correct=data["correct"],
            incorrect=data["incorrect"],
            accuracy=(data["correct"] / data["total"]) if data["total"] > 0 else 0.0,
        )
        for kind, data in by_kind.items()
        if data["total"] > 0
    ]

    accuracy_by_confidence = [
        Wc2026BenchmarkBucketAccuracy(
            confidence=label,
            accuracy=(data["correct"] / data["total"]) if data["total"] > 0 else 0.0,
            count=data["total"],
        )
        for label, data in sorted(by_conf.items(), key=lambda x: _confidence_order(x[0]))
    ]

    accuracy_by_period = [
        Wc2026BenchmarkPeriodAccuracy(
            period=p,
            accuracy=(d["correct"] / d["total"]) if d["total"] > 0 else 0.0,
            correct=d["correct"],
            total=d["total"],
        )
        for p, d in sorted(by_period.items(), key=lambda x: x[0])
    ]

    summary = Wc2026BenchmarkSummary(
        total_matches=total,
        correct=correct,
        incorrect=incorrect,
        pending=pending,
        accuracy=accuracy,
        accuracy_by_kind=accuracy_by_kind,
        accuracy_by_confidence=accuracy_by_confidence,
        accuracy_by_period=accuracy_by_period,
    )

    holdout: Optional[Wc2026ModelEvaluation] = None
    artifact = wc2026_prediction._BT_ARTIFACT
    if artifact is not None:
        metrics = _get_evaluation_metrics(artifact)
        if metrics is not None:
            holdout = Wc2026ModelEvaluation(**metrics)

    message: Optional[str] = None
    if total == 0 and pending == 0:
        message = (
            "No predictions yet. Once the scheduler snapshots upcoming WC2026 "
            "fixtures (or the tournament starts producing results), they will "
            "appear here. The holdout block is the model's training-time "
            "evaluation in the meantime."
        )
    elif total == 0 and pending > 0:
        message = (
            f"{pending} prediction(s) snapshotted but no resolved matches yet. "
            "Live accuracy will appear once results are scraped."
        )

    return Wc2026BenchmarkResponse(
        summary=summary,
        matches=matches,
        holdout=holdout,
        message=message,
    )


# ---------- Registration helper ---------------------------------------------

def register_wc2026_routes(
    app: FastAPI,
    get_current_user: Callable[..., Any],
    limiter: Any = None,
) -> None:
    """
    Attach WC2026 routes to an existing FastAPI app.

    Args:
        app: The FastAPI app instance from `app/api.py`.
        get_current_user: The JWT-validating dependency from `app/api.py`.
        limiter: Optional slowapi Limiter from `app/api.py`. When provided,
            POST /wc2026/predict is rate-limited per remote IP (same policy
            as the PSL /predict endpoint). Optional so existing test
            fixtures that call this helper without a limiter still pass.
    """

    # Resolve an effective rate-limit decorator that's a no-op when no
    # limiter was supplied (keeps tests / standalone use simple).
    if limiter is not None:
        _wc_predict_limit = limiter.limit("20/minute")
    else:
        def _wc_predict_limit(fn):  # type: ignore[misc]
            return fn

    # Make sure the per-user predictions table exists. This is the same
    # DDL as migration 004 and is safe to run on every startup; it lets
    # fresh Railway deploys serve PUT /wc2026/predictions immediately
    # without an out-of-band migration step.
    _ensure_user_predictions_schema()
    _ensure_wc_predictions_schema()

    @app.get("/groups/standings", response_model=GroupStandingsResponse)
    async def get_groups_standings() -> GroupStandingsResponse:
        try:
            return _build_groups_response()
        except Exception as exc:
            logger.error(f"[wc2026] /groups/standings failed: {exc}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to load group standings.",
            )

    @app.post(
        "/groups/standings/refresh",
        response_model=GroupStandingsRefreshResponse,
    )
    async def refresh_groups_standings(
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> GroupStandingsRefreshResponse:
        _require_admin(current_user)
        try:
            from jobs.fifa_scraper import scrape_groups

            scrape_groups()
        except Exception as exc:
            logger.error(f"[wc2026] refresh failed: {exc}", exc_info=True)
            raise HTTPException(
                status_code=502,
                detail=f"FIFA scrape failed: {exc}",
            )

        _, latest = _load_standings_rows()
        return GroupStandingsRefreshResponse(
            message="Group standings refresh triggered.",
            updated_at=_format_iso(latest),
        )

    @app.get("/wc2026/fixtures", response_model=WcFixturesResponse)
    async def get_wc2026_fixtures(
        date: Optional[str] = Query(
            None,
            description="YYYY-MM-DD — return only fixtures on this exact date.",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
        days: int = Query(
            7,
            ge=1,
            le=60,
            description=(
                "Inclusive day window from today (ignored when `date` is set). "
                "Defaults to 7 so the Fixtures tab shows roughly a week of matches."
            ),
        ),
    ) -> WcFixturesResponse:
        """
        Return WC2026 fixtures for a daily / windowed view.

        Public on purpose — fixture lists are not the model output we gate;
        the pre-match probability triplet is included as a convenience for
        the front-page Fixtures tab, but the schedule itself is published
        information.

        Two modes:
          * `?date=YYYY-MM-DD`  -> matches on that exact date.
          * default              -> today through today+`days` (inclusive).
        """
        try:
            if date is not None:
                try:
                    target = _date.fromisoformat(date)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="`date` must be a valid YYYY-MM-DD string.",
                    )
                date_from = target
                date_to = target
            else:
                date_from = _date.today()
                # `days=7` => today + 6 future days (an inclusive window of 7
                # calendar days), matching the natural "next week" intuition.
                date_to = date_from + timedelta(days=max(days - 1, 0))

            return _build_fixtures_response(date_from, date_to)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                f"[wc2026] /wc2026/fixtures failed: {exc}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to load WC2026 fixtures.",
            )

    @app.get("/wc2026/teams", response_model=TeamsResponse)
    async def get_wc2026_teams() -> TeamsResponse:
        """
        Return the 48 nations in the WC2026 draw, alphabetically sorted.

        Public — used by the /wc2026 Predict tab to populate the home/away
        dropdowns with national teams instead of PSL clubs.
        """
        teams = sorted({t for teams in STATIC_GROUPS.values() for t in teams})
        return TeamsResponse(teams=teams)

    @app.get("/wc2026/model/status", response_model=Wc2026ModelStatusResponse)
    async def get_wc2026_model_status() -> Wc2026ModelStatusResponse:
        """
        Return live WC2026 model status for the /wc2026 Status tab.

        Public — exposes the model_version, training-set size, and the
        in-sample evaluation metrics produced by `core.wc2026_model.evaluate`.
        No secrets / fitted strengths are surfaced.

        If the loaded artifact predates the metric-bake-in change (#issue),
        metrics are lazily recomputed from the on-disk H2H CSV and cached
        in memory. The frontend can disambiguate the two via
        `evaluation.evaluation_kind`.
        """
        artifact = wc2026_prediction._BT_ARTIFACT
        serving_with = wc2026_prediction._model_in_use()

        if artifact is None:
            return Wc2026ModelStatusResponse(
                status="unavailable",
                serving_with=serving_with,
            )

        evaluation_payload: Optional[Wc2026ModelEvaluation] = None
        metrics = _get_evaluation_metrics(artifact)
        if metrics is not None:
            evaluation_payload = Wc2026ModelEvaluation(**metrics)

        return Wc2026ModelStatusResponse(
            status="ready",
            model_version=artifact.model_version,
            serving_with=serving_with,
            teams_count=len(artifact.teams),
            n_matches=int(artifact.n_matches),
            evaluation=evaluation_payload,
        )

    @app.get("/wc2026/benchmark", response_model=Wc2026BenchmarkResponse)
    async def get_wc2026_benchmark(
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> Wc2026BenchmarkResponse:
        """
        Performance of the WC2026 BT model: snapshotted predictions vs
        actual results.

        Reads only resolved rows (``wc_predictions.resolved_at IS NOT
        NULL``) for the match table; the snapshot job populates the
        rows insert-only before kickoff so the model is never re-run on
        the request path. Each row carries a ``snapshot_kind``:

        - ``pre_match``   - inserted before kickoff. Honest pre-match.
        - ``retroactive`` - inserted after kickoff for the early-tournament
          backfill. Defensible because the WC2026 artifact is offline-only,
          but flagged so consumers can isolate the honest subset.

        Auth-required so the page matches the existing PSL ``/benchmark``
        ergonomics; the existing Benchmark frontend handles 401 by
        rendering the LoginPrompt.
        """
        try:
            return _build_wc_benchmark_response()
        except Exception as exc:
            logger.error(
                f"[wc2026] /wc2026/benchmark failed: {exc}", exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to load WC2026 benchmark.",
            )

    @app.get("/wc2026/predictions", response_model=UserPredictionsResponse)
    async def get_wc2026_user_predictions(
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> UserPredictionsResponse:
        """Return all WC2026 picks the current user has saved."""
        try:
            rows = _load_user_predictions(int(current_user["user_id"]))
        except Exception as exc:
            logger.error(
                f"[wc2026] /wc2026/predictions failed: {exc}", exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to load your saved predictions.",
            )

        predictions = [
            UserPrediction(
                fixture_id=int(r["fixture_id"]),
                group_name=r.get("group_name") or None,
                match_date=str(r["match_date"])[:10],
                kickoff_time=r.get("kickoff_time") or None,
                home_team=r["home_team"],
                away_team=r["away_team"],
                status=r.get("status") or "scheduled",
                home_goals=(
                    int(r["home_goals"])
                    if r.get("home_goals") is not None
                    and r.get("status") in ("live", "completed")
                    else None
                ),
                away_goals=(
                    int(r["away_goals"])
                    if r.get("away_goals") is not None
                    and r.get("status") in ("live", "completed")
                    else None
                ),
                predicted_outcome=r["predicted_outcome"],
                locked=_fixture_has_kicked_off(r),
                updated_at=_format_iso(r.get("updated_at")),
            )
            for r in rows
        ]
        return UserPredictionsResponse(predictions=predictions)

    @app.put(
        "/wc2026/predictions/group/{group_name}",
        response_model=UserPredictionsResponse,
    )
    async def upsert_wc2026_group_predictions(
        group_name: str,
        payload: GroupPredictionsSubmitRequest,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> UserPredictionsResponse:
        """
        Bulk-upsert the user's picks for a single WC2026 group.

        Each pick must reference a `fixture_id` that:
          * exists in `wc_fixtures`,
          * belongs to the requested `group_name`,
          * has not yet kicked off (i.e. `status == 'scheduled'`).

        The endpoint is all-or-nothing: if any pick fails validation the
        whole request 400s without persisting partial state. Editing
        previously-saved picks is allowed (the upsert simply rewrites the
        `predicted_outcome`); picks for matches that have already started
        are immutable and surfaced via the `locked` field in the response.
        """
        if not payload.picks:
            raise HTTPException(
                status_code=400, detail="At least one pick is required.",
            )

        user_id = int(current_user["user_id"])

        # Load this group's fixtures once and index by id so validation is
        # O(picks) rather than O(picks * fixtures).
        group_fixtures = _load_group_fixtures(group_name)
        by_id = {int(f["id"]): f for f in group_fixtures}
        if not by_id:
            raise HTTPException(
                status_code=404,
                detail=f"No fixtures found for {group_name!r}.",
            )

        # Validate every pick before writing anything.
        errors: List[str] = []
        seen_fixture_ids: set[int] = set()
        for pick in payload.picks:
            if pick.fixture_id in seen_fixture_ids:
                errors.append(
                    f"Fixture {pick.fixture_id} appears more than once in the request."
                )
                continue
            seen_fixture_ids.add(pick.fixture_id)

            fixture = by_id.get(pick.fixture_id)
            if fixture is None:
                errors.append(
                    f"Fixture {pick.fixture_id} is not part of {group_name}."
                )
                continue
            if _fixture_has_kicked_off(fixture):
                errors.append(
                    f"{fixture['home_team']} vs {fixture['away_team']} "
                    f"has already kicked off — predictions are locked."
                )

        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors))

        engine = get_db_engine()
        # We use INSERT … ON CONFLICT for Postgres but fall back to a
        # DELETE-then-INSERT on SQLite (used by tests) which doesn't honour
        # the same upsert grammar reliably across versions.
        dialect = engine.dialect.name
        with engine.begin() as conn:
            for pick in payload.picks:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            "DELETE FROM wc_user_predictions "
                            "WHERE user_id = :uid AND fixture_id = :fid"
                        ),
                        {"uid": user_id, "fid": pick.fixture_id},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO wc_user_predictions "
                            "(user_id, fixture_id, predicted_outcome) "
                            "VALUES (:uid, :fid, :outcome)"
                        ),
                        {
                            "uid": user_id,
                            "fid": pick.fixture_id,
                            "outcome": pick.predicted_outcome,
                        },
                    )
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO wc_user_predictions
                                (user_id, fixture_id, predicted_outcome)
                            VALUES (:uid, :fid, :outcome)
                            ON CONFLICT (user_id, fixture_id) DO UPDATE SET
                                predicted_outcome = EXCLUDED.predicted_outcome,
                                updated_at = NOW()
                            """
                        ),
                        {
                            "uid": user_id,
                            "fid": pick.fixture_id,
                            "outcome": pick.predicted_outcome,
                        },
                    )

        # Round-trip: re-read so the response reflects the persisted state
        # (handy for the frontend to refresh its local copy in one call).
        return await get_wc2026_user_predictions(current_user)  # type: ignore[arg-type]

    @app.get(
        "/predictions/group/{group_name}",
        response_model=GroupPredictionsResponse,
    )
    async def get_group_predictions(
        group_name: str,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> GroupPredictionsResponse:
        try:
            return _build_group_predictions(group_name)
        except Exception as exc:
            logger.error(
                f"[wc2026] /predictions/group/{group_name} failed: {exc}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to compute group predictions.",
            )

    @app.post("/wc2026/predict", response_model=WcPredictionResponse)
    @_wc_predict_limit
    async def predict_wc2026_match(
        request: Request,  # noqa: ARG001 — required by slowapi keying
        payload: WcPredictionRequest,
    ) -> WcPredictionResponse:
        """
        Predict outcome probabilities for an arbitrary WC2026 match.

        Public + rate-limited (same policy as the PSL /predict endpoint).
        Uses the FIFA-Elo Phase 1 model in `core/wc2026_prediction.py` so
        national-team probabilities are coherent (the PSL model only knows
        about PSL clubs and returns near-uniform output for national teams).

        Rejects unknown team names with HTTP 400 — better to fail loudly
        than silently fall back to the default rank and ship a misleading
        probability triplet.
        """
        home = payload.home_team.strip()
        away = payload.away_team.strip()

        if not home or not away:
            raise HTTPException(
                status_code=400,
                detail="home_team and away_team are required.",
            )
        if home.lower() == away.lower():
            raise HTTPException(
                status_code=400,
                detail="home_team and away_team must be different.",
            )

        # Reject unknown team names explicitly. `wc2026_prediction.predict`
        # would otherwise silently use DEFAULT_RANK and emit a misleading
        # probability triplet — better to fail loudly so the frontend can
        # surface a clear error to the user.
        if not has_rank(home):
            raise HTTPException(
                status_code=400,
                detail=f"Unknown team: {home}.",
            )
        if not has_rank(away):
            raise HTTPException(
                status_code=400,
                detail=f"Unknown team: {away}.",
            )

        try:
            probabilities = wc2026_prediction.predict(home, away)
            outcome = wc2026_prediction.outcome_from_probs(probabilities)
            confidence = probabilities[outcome]
        except Exception as exc:
            logger.error(
                f"[wc2026] /wc2026/predict failed for {home} vs {away}: {exc}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to compute WC2026 prediction.",
            )

        return WcPredictionResponse(
            home_team=home,
            away_team=away,
            probabilities=probabilities,
            predicted_outcome=outcome,
            confidence=confidence,
            model_version=wc2026_prediction.MODEL_VERSION,
        )

    # ---------- Phase 1 payment / unlock stubs --------------------------------

    @app.post("/payments/paystack/init")
    async def paystack_init(
        payload: PaystackInitRequest,  # noqa: ARG001 — accepted for contract
        current_user: Dict[str, Any] = Depends(get_current_user),  # noqa: ARG001
    ) -> Dict[str, Any]:
        raise HTTPException(
            status_code=503,
            detail="Payments coming soon. WC2026 prediction unlocks launch after kickoff.",
        )

    @app.get("/payments/paystack/verify")
    async def paystack_verify(
        reference: str = Query(..., min_length=1),  # noqa: ARG001
        current_user: Dict[str, Any] = Depends(get_current_user),  # noqa: ARG001
    ) -> Dict[str, Any]:
        return {"success": False}

    @app.get("/unlocks")
    async def get_unlocks(
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Return the list of unlocked item_keys for the current user.

        Phase 1 returns an empty list (payments not yet live) but already
        reads from the `unlocks` table so Phase 2 only needs to flip the
        Paystack init/verify stubs.
        """
        engine = get_db_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT item_key FROM unlocks WHERE user_id = :uid"
                ),
                {"uid": current_user["user_id"]},
            ).fetchall()
        return {"unlocks": [r[0] for r in rows]}

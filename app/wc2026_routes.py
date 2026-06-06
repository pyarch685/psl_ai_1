"""
FastAPI routes for the WC2026 (FIFA World Cup 2026) surface.

Additive — these endpoints live alongside the existing PSL routes and do not
change any PSL behaviour. They are mounted at the bottom of `app/api.py` via
`register_wc2026_routes(app)`.

Phase 1 contract (matches `src/wc2026/lib/api.ts`):

- GET  /groups/standings              public  (live standings + draw fallback)
- POST /groups/standings/refresh      auth    (admin allowlist; triggers scraper)
- GET  /predictions/group/{name}      auth    (FIFA-Elo predictions per group)
- POST /payments/paystack/init        auth    (Phase 1 stub — 503)
- GET  /payments/paystack/verify      auth    (Phase 1 stub — {success: false})
- GET  /unlocks                       auth    (Phase 1 stub — {unlocks: []})
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from core import wc2026_prediction
from core.fifa_rankings import has_rank
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


class GroupWinnerPrediction(BaseModel):
    team: str
    probability: float


class GroupPredictionsResponse(BaseModel):
    matches: List[GroupMatchPrediction]
    winner: Optional[GroupWinnerPrediction] = None


class PaystackInitRequest(BaseModel):
    kind: str
    item_key: str
    amount_usd: float
    callback_url: Optional[str] = None


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

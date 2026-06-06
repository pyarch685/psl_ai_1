"""
Prediction persistence layer.

Centralizes reads and writes against the ``predictions`` table so the
scheduler can:

- Freeze pre-match probabilities for every upcoming fixture
  (one row per ``(match_date, home_team, away_team)``).
- Backfill the actual outcome once the match is played.
- Expose resolved rows for downstream ML evaluation.

Writes are insert-only (``ON CONFLICT DO NOTHING``) so a prediction made
before kickoff is never silently overwritten when the model changes.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.prediction import ModelArtifacts, load_fixtures, predict_softmax
from db.engine import get_db_engine

logger = logging.getLogger(__name__)


def model_version_label(model: ModelArtifacts) -> str:
    """
    Derive a stable, human-readable version string from a trained model.

    The label is stored in ``predictions.model_version`` so we can later
    group resolved predictions by the model that produced them.
    """
    params = model.params or {}
    model_type = str(params.get("model", "unknown")).replace(" ", "_")
    k = params.get("k", "?")
    window = params.get("window", "?")
    calibrated = "cal" if params.get("calibrated") else "raw"
    return f"{model_type}-k{k}-w{window}-{calibrated}"


def _outcome_from_probs(probs: Dict[str, float]) -> tuple[str, float]:
    """Return (predicted_outcome, confidence) for a ``predict_softmax`` result."""
    predicted = max(probs.items(), key=lambda item: item[1])[0]
    return predicted, float(probs[predicted])


def _outcome_from_score(home_goals: int, away_goals: int) -> str:
    """Map a final score to one of 'Home' / 'Draw' / 'Away'."""
    if home_goals > away_goals:
        return "Home"
    if home_goals == away_goals:
        return "Draw"
    return "Away"


def insert_prediction_if_absent(
    *,
    engine: Engine,
    match_date: date,
    home_team: str,
    away_team: str,
    probs: Dict[str, float],
    model_version: str,
) -> bool:
    """
    Insert a single pre-match prediction.

    Returns ``True`` if a new row was inserted, ``False`` if a row for this
    fixture already existed (unique constraint hit).
    """
    predicted_outcome, confidence = _outcome_from_probs(probs)

    insert_sql = text(
        """
        INSERT INTO predictions (
            match_date, home_team, away_team,
            home_win_prob, draw_prob, away_win_prob,
            predicted_outcome, confidence, model_version
        ) VALUES (
            :match_date, :home_team, :away_team,
            :home_win_prob, :draw_prob, :away_win_prob,
            :predicted_outcome, :confidence, :model_version
        )
        ON CONFLICT (match_date, home_team, away_team) DO NOTHING
        RETURNING id
        """
    )

    with engine.begin() as conn:
        result = conn.execute(
            insert_sql,
            {
                "match_date": match_date,
                "home_team": home_team,
                "away_team": away_team,
                "home_win_prob": float(probs.get("Home", 0.0)),
                "draw_prob": float(probs.get("Draw", 0.0)),
                "away_win_prob": float(probs.get("Away", 0.0)),
                "predicted_outcome": predicted_outcome,
                "confidence": confidence,
                "model_version": model_version,
            },
        )
        return result.fetchone() is not None


def persist_upcoming_fixture_predictions(
    model: Optional[ModelArtifacts],
    days: int = 30,
    engine: Optional[Engine] = None,
) -> Dict[str, int]:
    """
    Predict every upcoming fixture in the next ``days`` and insert
    rows for any fixtures not already in ``predictions``.

    Skips quietly when the model is not trained yet. Individual
    prediction failures are logged but do not abort the batch.

    Returns counts: ``{"considered": N, "inserted": M, "skipped": K, "failed": F}``.
    """
    stats = {"considered": 0, "inserted": 0, "skipped": 0, "failed": 0}

    if model is None:
        logger.info(
            "[prediction_store] No trained model available; "
            "skipping prediction persistence run"
        )
        return stats

    engine = engine or get_db_engine()
    version = model_version_label(model)

    try:
        fixtures = load_fixtures("fixtures")
    except Exception as exc:
        logger.error(
            f"[prediction_store] Failed to load fixtures: {exc}", exc_info=True
        )
        return stats

    if fixtures.empty:
        return stats

    fixtures["date"] = pd.to_datetime(fixtures["date"], errors="coerce")
    today = pd.Timestamp.today().normalize()
    end_date = today + pd.Timedelta(days=days)

    # Match the upcoming filter used by /fixtures so persisted rows
    # mirror what the API would have served.
    status_series = fixtures["status"].fillna("")
    excluded = status_series.isin(["completed", "postponed", "delayed"])
    upcoming = fixtures[
        (fixtures["date"] >= today)
        & (fixtures["date"] <= end_date)
        & (~excluded)
    ].copy()

    for _, row in upcoming.iterrows():
        stats["considered"] += 1

        home_team = str(row.home_team).strip()
        away_team = str(row.away_team).strip()
        match_date_val = row.date

        if pd.isna(match_date_val) or not home_team or not away_team:
            stats["failed"] += 1
            continue

        try:
            probs = predict_softmax(model, home_team, away_team)
            inserted = insert_prediction_if_absent(
                engine=engine,
                match_date=match_date_val.date(),
                home_team=home_team,
                away_team=away_team,
                probs=probs,
                model_version=version,
            )
            if inserted:
                stats["inserted"] += 1
            else:
                stats["skipped"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                f"[prediction_store] Failed to persist prediction for "
                f"{home_team} vs {away_team}: {exc}"
            )

    logger.info(
        "[prediction_store] persist_upcoming_fixture_predictions: "
        f"considered={stats['considered']} inserted={stats['inserted']} "
        f"skipped={stats['skipped']} failed={stats['failed']}"
    )
    return stats


def resolve_completed_predictions(
    engine: Optional[Engine] = None,
) -> Dict[str, int]:
    """
    Backfill ``actual_*`` columns for predictions whose matches have
    final scores in the ``fixtures`` table.

    Only rows with ``resolved_at IS NULL`` are updated, so a resolved row
    is never touched again.

    Returns ``{"resolved": N}``.
    """
    engine = engine or get_db_engine()

    select_sql = text(
        """
        SELECT p.id, f.home_goals, f.away_goals, p.predicted_outcome
        FROM predictions p
        JOIN fixtures f
          ON f.date = p.match_date
         AND f.home_team = p.home_team
         AND f.away_team = p.away_team
        WHERE p.resolved_at IS NULL
          AND f.home_goals IS NOT NULL
          AND f.away_goals IS NOT NULL
        """
    )

    update_sql = text(
        """
        UPDATE predictions
        SET actual_outcome = :actual_outcome,
            actual_home_goals = :actual_home_goals,
            actual_away_goals = :actual_away_goals,
            is_correct = :is_correct,
            resolved_at = NOW()
        WHERE id = :id
          AND resolved_at IS NULL
        """
    )

    resolved = 0
    with engine.begin() as conn:
        rows = conn.execute(select_sql).fetchall()
        for row in rows:
            pred_id, home_goals, away_goals, predicted_outcome = row
            actual = _outcome_from_score(int(home_goals), int(away_goals))
            conn.execute(
                update_sql,
                {
                    "id": pred_id,
                    "actual_outcome": actual,
                    "actual_home_goals": int(home_goals),
                    "actual_away_goals": int(away_goals),
                    "is_correct": predicted_outcome == actual,
                },
            )
            resolved += 1

    if resolved:
        logger.info(
            f"[prediction_store] resolve_completed_predictions: resolved={resolved}"
        )
    return {"resolved": resolved}


def load_resolved_predictions(
    engine: Optional[Engine] = None,
    since: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Return resolved predictions for downstream ML evaluation.

    Not wired into the training pipeline yet; callers (notebooks,
    follow-up metrics module) read from here.
    """
    engine = engine or get_db_engine()

    base_sql = """
        SELECT match_date, home_team, away_team,
               home_win_prob, draw_prob, away_win_prob,
               predicted_outcome, confidence, model_version,
               actual_outcome, actual_home_goals, actual_away_goals,
               is_correct, resolved_at, created_at
        FROM predictions
        WHERE resolved_at IS NOT NULL
    """
    params: Dict[str, Any] = {}
    if since is not None:
        base_sql += " AND resolved_at >= :since"
        params["since"] = since
    base_sql += " ORDER BY match_date"

    with engine.connect() as conn:
        rows = conn.execute(text(base_sql), params).mappings().all()
    return [dict(row) for row in rows]


def get_prediction_for_fixture(
    *,
    match_date: date,
    home_team: str,
    away_team: str,
    engine: Optional[Engine] = None,
) -> Optional[Dict[str, Any]]:
    """
    Look up the stored prediction for a single fixture.

    Returns ``None`` when the row does not exist yet (e.g. the scheduler
    has not run since the fixture was scraped). Callers can fall back to
    live computation in that case.
    """
    engine = engine or get_db_engine()
    select_sql = text(
        """
        SELECT match_date, home_team, away_team,
               home_win_prob, draw_prob, away_win_prob,
               predicted_outcome, confidence, model_version,
               actual_outcome, actual_home_goals, actual_away_goals,
               is_correct, resolved_at, created_at
        FROM predictions
        WHERE match_date = :match_date
          AND home_team = :home_team
          AND away_team = :away_team
        """
    )
    with engine.connect() as conn:
        row = conn.execute(
            select_sql,
            {
                "match_date": match_date,
                "home_team": home_team,
                "away_team": away_team,
            },
        ).mappings().first()
    return dict(row) if row else None


def load_recent_resolved_predictions(
    limit: int = 200,
    engine: Optional[Engine] = None,
) -> List[Dict[str, Any]]:
    """
    Return the most recent resolved predictions for the benchmark page.

    Ordered by ``match_date DESC`` so the UI shows the latest results first.
    """
    engine = engine or get_db_engine()
    select_sql = text(
        """
        SELECT match_date, home_team, away_team,
               home_win_prob, draw_prob, away_win_prob,
               predicted_outcome, confidence, model_version,
               actual_outcome, actual_home_goals, actual_away_goals,
               is_correct, resolved_at
        FROM predictions
        WHERE resolved_at IS NOT NULL
        ORDER BY match_date DESC
        LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(select_sql, {"limit": int(limit)}).mappings().all()
    return [dict(row) for row in rows]

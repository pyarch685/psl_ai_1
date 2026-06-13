"""
WC2026 prediction persistence layer.

Mirrors :mod:`core.prediction_store` for the World Cup surface but
operates on ``wc_fixtures`` / ``wc_predictions`` instead of the PSL
``fixtures`` / ``predictions`` tables.

Three responsibilities:

1. **Snapshot** the BT model's prediction for every WC fixture that does
   not yet have a row, tagging each row with a :data:`snapshot_kind`:

   - ``'pre_match'``   - the fixture's kickoff is still in the future at
     insert time. This is the honest pre-match probability; what the
     model believed before the result was known.
   - ``'retroactive'`` - the fixture's kickoff has already passed.
     Defensible only because the WC2026 BT artifact is offline-trained
     (see :mod:`core.wc2026_train`) and there is no scheduled retrain
     job, so the prediction today is identical to what the model would
     have produced before kickoff. Surfacing the kind lets API and UI
     consumers isolate the honest pre-match subset.

2. **Backfill** the actual outcome on rows whose ``wc_fixtures.status``
   has flipped to ``'completed'`` and have final goals.

3. **Load** resolved rows (joined with ``wc_fixtures`` for date / teams /
   stage) for the ``/wc2026/benchmark`` endpoint.

Writes are insert-only (``ON CONFLICT (fixture_id) DO NOTHING``). Reads
return plain dicts so the API layer doesn't need to know about
SQLAlchemy.
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core import wc2026_prediction
from db.engine import get_db_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _outcome_from_probs(probs: Dict[str, float]) -> tuple[str, float]:
    """Return ``(predicted_outcome, confidence)`` for a 3-way prob dict."""
    predicted, prob = max(probs.items(), key=lambda kv: kv[1])
    return predicted, float(prob)


def _outcome_from_score(home_goals: int, away_goals: int) -> str:
    """Map a final score to ``'Home'`` / ``'Draw'`` / ``'Away'``."""
    if home_goals > away_goals:
        return "Home"
    if home_goals == away_goals:
        return "Draw"
    return "Away"


def _parse_kickoff_dt(match_date: Any, kickoff_time: Optional[str]) -> Optional[datetime]:
    """
    Combine ``wc_fixtures.match_date`` (date) and the free-form
    ``kickoff_time`` (string like ``'18:00'``, ``'18:00:00'``, or empty)
    into a naive UTC datetime.

    Returns ``None`` when the date is missing or unparseable, and falls
    back to end-of-day when the time is missing - so a row with a
    real date but no time still snapshots as ``'pre_match'`` for the
    rest of that calendar day.
    """
    if match_date is None:
        return None

    base_date = match_date
    if isinstance(match_date, str):
        try:
            base_date = datetime.fromisoformat(match_date).date()
        except ValueError:
            return None
    elif hasattr(match_date, "date") and not isinstance(match_date, datetime):
        # SQLAlchemy returns ``datetime.date`` for DATE columns.
        pass
    elif isinstance(match_date, datetime):
        base_date = match_date.date()

    parsed_time: Optional[time] = None
    if kickoff_time:
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                parsed_time = datetime.strptime(kickoff_time.strip(), fmt).time()
                break
            except ValueError:
                continue

    if parsed_time is None:
        # No time on the row - treat the whole match_date as a single
        # day window and call kickoff "end of day". This biases new
        # snapshots toward 'pre_match' for the day the fixture is
        # scheduled, which is the conservative choice.
        parsed_time = time(23, 59, 59)

    return datetime.combine(base_date, parsed_time)


def _classify_snapshot_kind(
    *,
    match_date: Any,
    kickoff_time: Optional[str],
    now: Optional[datetime] = None,
) -> str:
    """
    Decide whether an as-of-now snapshot for a given fixture is honest
    pre-kickoff (``'pre_match'``) or after-the-fact (``'retroactive'``).
    """
    if now is None:
        now = datetime.utcnow()
    kickoff = _parse_kickoff_dt(match_date, kickoff_time)
    if kickoff is None:
        # Fall back to retroactive when we can't tell - it's the
        # honest, conservative choice.
        return "retroactive"
    return "pre_match" if kickoff > now else "retroactive"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


_INSERT_PREDICTION_SQL = text(
    """
    INSERT INTO wc_predictions (
        fixture_id, predicted_outcome,
        prob_home, prob_draw, prob_away,
        confidence, model_version, snapshot_kind
    ) VALUES (
        :fixture_id, :predicted_outcome,
        :prob_home, :prob_draw, :prob_away,
        :confidence, :model_version, :snapshot_kind
    )
    ON CONFLICT (fixture_id) DO NOTHING
    RETURNING id, snapshot_kind
    """
)


def _load_unsnapshotted_fixtures(engine: Engine) -> List[Dict[str, Any]]:
    """
    Return every wc_fixtures row that has no wc_predictions row yet.

    Includes past fixtures - the snapshot job tags them as
    'retroactive' rather than skipping them, since the WC2026 model is
    offline-trained and gives the same prediction today as it would
    have pre-match.
    """
    sql = text(
        """
        SELECT f.id, f.match_date, f.kickoff_time,
               f.home_team, f.away_team
        FROM wc_fixtures f
        LEFT JOIN wc_predictions p ON p.fixture_id = f.id
        WHERE p.id IS NULL
        ORDER BY f.match_date,
                 (f.kickoff_time IS NULL),
                 f.kickoff_time,
                 f.id
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    return [dict(r) for r in rows]


def snapshot_wc_predictions(
    engine: Optional[Engine] = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """
    Predict every WC fixture not yet in ``wc_predictions`` and INSERT.

    Insert-only: a fixture with an existing row is left untouched so the
    original probabilities (and ``snapshot_kind``) survive.

    Returns counts::

        {
            "considered": N,
            "inserted_pre_match": A,
            "inserted_retroactive": B,
            "skipped": C,    # ON CONFLICT path (rare; LEFT JOIN already filters)
            "failed": D,     # exception raised while predicting
        }
    """
    stats = {
        "considered": 0,
        "inserted_pre_match": 0,
        "inserted_retroactive": 0,
        "skipped": 0,
        "failed": 0,
    }

    if wc2026_prediction._BT_ARTIFACT is None:
        # Without a trained BT artifact we'd be storing FIFA-Elo prior
        # predictions, which is fine but worth noting in logs so the
        # snapshot job's silent success is explainable.
        logger.info(
            "[wc_prediction_store] BT artifact unavailable; "
            "snapshots will use the FIFA-Elo fallback model."
        )

    engine = engine or get_db_engine()
    model_version = wc2026_prediction._model_in_use()
    if not model_version:
        model_version = "wc2026_unknown"

    fixtures = _load_unsnapshotted_fixtures(engine)
    stats["considered"] = len(fixtures)
    if not fixtures:
        return stats

    for row in fixtures:
        fixture_id = int(row["id"])
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            stats["failed"] += 1
            continue

        try:
            probs = wc2026_prediction.predict(home_team, away_team)
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                f"[wc_prediction_store] predict() failed for "
                f"{home_team} vs {away_team}: {exc}"
            )
            continue

        predicted, confidence = _outcome_from_probs(probs)
        kind = _classify_snapshot_kind(
            match_date=row.get("match_date"),
            kickoff_time=row.get("kickoff_time"),
            now=now,
        )

        try:
            with engine.begin() as conn:
                inserted = conn.execute(
                    _INSERT_PREDICTION_SQL,
                    {
                        "fixture_id": fixture_id,
                        "predicted_outcome": predicted,
                        "prob_home": float(probs.get("Home", 0.0)),
                        "prob_draw": float(probs.get("Draw", 0.0)),
                        "prob_away": float(probs.get("Away", 0.0)),
                        "confidence": float(confidence),
                        "model_version": model_version,
                        "snapshot_kind": kind,
                    },
                ).fetchone()
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                f"[wc_prediction_store] INSERT failed for fixture {fixture_id}: {exc}"
            )
            continue

        if inserted is None:
            stats["skipped"] += 1
            continue

        if kind == "pre_match":
            stats["inserted_pre_match"] += 1
        else:
            stats["inserted_retroactive"] += 1

    logger.info(
        "[wc_prediction_store] snapshot_wc_predictions: "
        f"considered={stats['considered']} "
        f"inserted_pre_match={stats['inserted_pre_match']} "
        f"inserted_retroactive={stats['inserted_retroactive']} "
        f"skipped={stats['skipped']} failed={stats['failed']}"
    )
    return stats


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


_BACKFILL_SELECT_SQL = text(
    """
    SELECT p.id AS pred_id,
           p.predicted_outcome,
           f.home_goals,
           f.away_goals
    FROM wc_predictions p
    JOIN wc_fixtures f ON f.id = p.fixture_id
    WHERE p.resolved_at IS NULL
      AND f.status = 'completed'
      AND f.home_goals IS NOT NULL
      AND f.away_goals IS NOT NULL
    """
)


_BACKFILL_UPDATE_SQL = text(
    """
    UPDATE wc_predictions
    SET actual_outcome = :actual_outcome,
        actual_home_goals = :actual_home_goals,
        actual_away_goals = :actual_away_goals,
        is_correct = :is_correct,
        resolved_at = CURRENT_TIMESTAMP
    WHERE id = :id
      AND resolved_at IS NULL
    """
)


def backfill_completed_wc_predictions(
    engine: Optional[Engine] = None,
) -> Dict[str, int]:
    """
    Fill ``actual_*`` columns on rows whose fixture has played.

    Only rows where ``resolved_at IS NULL`` are touched, so a resolved
    row is never updated again.
    """
    engine = engine or get_db_engine()
    resolved = 0
    with engine.begin() as conn:
        rows = conn.execute(_BACKFILL_SELECT_SQL).mappings().all()
        for row in rows:
            try:
                home_goals = int(row["home_goals"])
                away_goals = int(row["away_goals"])
            except (TypeError, ValueError):
                continue
            actual = _outcome_from_score(home_goals, away_goals)
            conn.execute(
                _BACKFILL_UPDATE_SQL,
                {
                    "id": row["pred_id"],
                    "actual_outcome": actual,
                    "actual_home_goals": home_goals,
                    "actual_away_goals": away_goals,
                    "is_correct": row["predicted_outcome"] == actual,
                },
            )
            resolved += 1

    if resolved:
        logger.info(
            f"[wc_prediction_store] backfill_completed_wc_predictions: "
            f"resolved={resolved}"
        )
    return {"resolved": resolved}


# ---------------------------------------------------------------------------
# Read paths
# ---------------------------------------------------------------------------


def load_resolved_wc_predictions(
    limit: int = 200,
    engine: Optional[Engine] = None,
) -> List[Dict[str, Any]]:
    """
    Return resolved wc_predictions joined with wc_fixtures, newest first.

    Each row is a flat dict with the columns the
    ``GET /wc2026/benchmark`` endpoint needs. ``snapshot_kind`` is
    surfaced so the API can split accuracy by kind without a second
    query.
    """
    engine = engine or get_db_engine()
    sql = text(
        """
        SELECT
            p.id, p.fixture_id,
            p.predicted_outcome, p.prob_home, p.prob_draw, p.prob_away,
            p.confidence, p.model_version, p.snapshot_kind, p.predicted_at,
            p.actual_outcome, p.actual_home_goals, p.actual_away_goals,
            p.is_correct, p.resolved_at,
            f.match_date, f.kickoff_time, f.group_name, f.stage,
            f.home_team, f.away_team
        FROM wc_predictions p
        JOIN wc_fixtures f ON f.id = p.fixture_id
        WHERE p.resolved_at IS NOT NULL
        ORDER BY f.match_date DESC,
                 (f.kickoff_time IS NULL),
                 f.kickoff_time DESC,
                 p.id DESC
        LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"limit": int(limit)}).mappings().all()
    return [dict(r) for r in rows]


def count_pending_wc_predictions(engine: Optional[Engine] = None) -> int:
    """
    Number of rows that have been snapshotted but not yet resolved.

    Used by the benchmark summary to surface ``pending`` separately
    from the accuracy denominator.
    """
    engine = engine or get_db_engine()
    sql = text(
        """
        SELECT COUNT(*) AS pending
        FROM wc_predictions
        WHERE resolved_at IS NULL
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql).mappings().first()
    return int(row["pending"]) if row else 0

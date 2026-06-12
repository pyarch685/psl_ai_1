"""
Background scheduler for PSL data updates.

Responsibilities:
- Periodically run scraping jobs
- Periodically retrain ML model
- Fail gracefully (never crash the app)
- Be started once at application startup

This module must remain lightweight and dependency-safe.
"""
import logging

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from jobs.fifa_scraper import scrape_groups as scrape_wc_groups
from jobs.scraper import update_fixtures, update_match_results

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# SCHEDULER CONFIGURATION
# -------------------------------------------------------------------

JOBSTORES = {
    "default": MemoryJobStore()
}

EXECUTORS = {
    "default": ThreadPoolExecutor(max_workers=5)
}

JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 300,  # seconds
}


# -------------------------------------------------------------------
# SCHEDULER INITIALIZATION
# -------------------------------------------------------------------

_scheduler = None


def retrain_model() -> None:
    """
    Retrain the prediction model with latest data.

    This function:
    - Loads all match data (historical + completed fixtures)
    - Trains a new model with default parameters
    - Saves the model to disk
    - Updates the global model cache if running in API context

    Fails gracefully - logs errors but doesn't crash the scheduler.
    """
    try:
        logger.info("[scheduler] Starting scheduled model retraining")
        
        # Import here to avoid circular dependencies
        from core.prediction import load_all_match_data, train_classifier
        from core.model_store import save_model
        
        # Load all match data
        all_match_data = load_all_match_data("matches", "fixtures")
        
        if len(all_match_data) < 50:
            logger.warning(
                f"[scheduler] Insufficient data for retraining: {len(all_match_data)} matches "
                "(need at least 50). Skipping retraining."
            )
            return
        
        logger.info(f"[scheduler] Training model on {len(all_match_data)} matches")
        
        # Train model with default parameters
        model = train_classifier(
            all_match_data,
            do_tune=True,
            calibrate=True,
            use_nn=True
        )
        
        # Save model to disk
        save_model(model)
        
        logger.info(
            f"[scheduler] ✓ Model retrained and saved successfully "
            f"(type: {model.params.get('model', 'Unknown')}, "
            f"teams: {len(model.team_elo)})"
        )
        print(
            f"[scheduler] ✓ Model retrained successfully on {len(all_match_data)} matches"
        )
        
        # Try to update global model cache if running in API context
        try:
            import app.api
            if hasattr(app.api, '_model_cache'):
                app.api._model_cache = model
                logger.info("[scheduler] Updated API model cache")
        except Exception:
            # Not running in API context, that's okay
            pass
            
    except Exception as e:
        logger.error(f"[scheduler] Failed to retrain model: {e}", exc_info=True)
        print(f"[scheduler] ⚠️  Model retraining failed: {e}")
        # Don't raise - fail gracefully


def _current_model() -> object:
    """
    Return the in-memory model from the API cache if available, otherwise
    load it from disk. Returns ``None`` when no model is trained yet.
    """
    try:
        import app.api as api_module
        cached = getattr(api_module, "_model_cache", None)
        if cached is not None:
            return cached
    except Exception:
        pass

    try:
        from core.model_store import load_model
        return load_model()
    except Exception as exc:
        logger.warning(f"[scheduler] Could not load model from disk: {exc}")
        return None


def persist_fixture_predictions() -> None:
    """
    Persist pre-match predictions for upcoming fixtures.

    Insert-only: predictions already in the table are never overwritten,
    preserving the original pre-match probabilities for ML evaluation.

    Fails gracefully - logs errors but doesn't crash the scheduler.
    """
    try:
        from core.prediction_store import persist_upcoming_fixture_predictions

        model = _current_model()
        if model is None:
            logger.info(
                "[scheduler] persist_fixture_predictions: no model available, skipping"
            )
            return

        stats = persist_upcoming_fixture_predictions(model)
        print(
            "[scheduler] ✓ persist_fixture_predictions: "
            f"inserted={stats['inserted']} skipped={stats['skipped']} "
            f"failed={stats['failed']} considered={stats['considered']}"
        )
    except Exception as exc:
        logger.error(
            f"[scheduler] Failed to persist fixture predictions: {exc}",
            exc_info=True,
        )
        print(f"[scheduler] ⚠️  persist_fixture_predictions failed: {exc}")


def resolve_prediction_outcomes() -> None:
    """
    Backfill ``actual_*`` columns on predictions whose matches now have
    final scores in the fixtures table.

    Fails gracefully - logs errors but doesn't crash the scheduler.
    """
    try:
        from core.prediction_store import resolve_completed_predictions

        stats = resolve_completed_predictions()
        if stats["resolved"]:
            print(
                f"[scheduler] ✓ resolve_prediction_outcomes: resolved={stats['resolved']}"
            )
    except Exception as exc:
        logger.error(
            f"[scheduler] Failed to resolve prediction outcomes: {exc}",
            exc_info=True,
        )
        print(f"[scheduler] ⚠️  resolve_prediction_outcomes failed: {exc}")


def start_scheduler() -> None:
    """
    Start the background scheduler.

    This function is idempotent: calling it multiple times will not
    start multiple schedulers.

    Registers five jobs:
    - update_match_results: Runs every hour
    - update_fixtures: Runs every hour
    - persist_fixture_predictions: Runs every hour (insert-only)
    - resolve_prediction_outcomes: Runs every hour
    - retrain_model: Runs every 7 days
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        print("[scheduler] Scheduler already running")
        return

    _scheduler = BackgroundScheduler(
        jobstores=JOBSTORES,
        executors=EXECUTORS,
        job_defaults=JOB_DEFAULTS,
        timezone="UTC",
    )

    # ---------------------------------------------------------------
    # JOB REGISTRATION
    # ---------------------------------------------------------------

    _scheduler.add_job(
        update_match_results,
        trigger="interval",
        hours=1,
        id="update_match_results",
        replace_existing=True,
    )

    _scheduler.add_job(
        update_fixtures,
        trigger="interval",
        hours=1,
        id="update_fixtures",
        replace_existing=True,
    )

    _scheduler.add_job(
        persist_fixture_predictions,
        trigger="interval",
        hours=1,
        id="persist_fixture_predictions",
        replace_existing=True,
    )

    _scheduler.add_job(
        resolve_prediction_outcomes,
        trigger="interval",
        hours=1,
        id="resolve_prediction_outcomes",
        replace_existing=True,
    )

    _scheduler.add_job(
        retrain_model,
        trigger="interval",
        days=7,
        id="retrain_model",
        replace_existing=True,
    )

    # WC2026: refresh FIFA group standings once per day. Phase 1 only ships
    # the groups scraper; fixtures/results scrapers land in Phase 2.
    _scheduler.add_job(
        scrape_wc_groups,
        trigger="interval",
        hours=24,
        id="scrape_wc_groups",
        replace_existing=True,
    )

    _scheduler.start()

    # Run scraper immediately on startup (don't wait for first interval)
    def _run_on_startup() -> None:
        try:
            update_match_results()
            update_fixtures()
            persist_fixture_predictions()
            resolve_prediction_outcomes()
            print("[scheduler] Startup scrape completed")
        except Exception as e:
            logger.warning(f"[scheduler] Startup scrape failed: {e}")
            print(f"[scheduler] Startup scrape failed: {e}")
        try:
            scrape_wc_groups()
        except Exception as e:
            logger.warning(f"[scheduler] Startup WC2026 groups scrape failed: {e}")
            print(f"[scheduler] Startup WC2026 groups scrape failed: {e}")

    # APScheduler's `BackgroundScheduler` doesn't expose its executor pool as
    # a public `.executors` attribute, so run the startup scrape on a plain
    # daemon thread. This still runs out-of-band from the web server and any
    # exceptions are swallowed inside `_run_on_startup`.
    try:
        import threading
        threading.Thread(target=_run_on_startup, daemon=True, name="startup-scrape").start()
    except Exception as e:
        logger.warning(f"[scheduler] Could not submit startup scrape: {e}")

    print("[scheduler] Scheduler started")
    print("[scheduler] Jobs registered:")
    for job in _scheduler.get_jobs():
        print(f"  - {job.id} (next run at {job.next_run_time})")


def shutdown_scheduler() -> None:
    """
    Gracefully shut down the scheduler.

    Stops all scheduled jobs and releases resources.
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("[scheduler] Scheduler stopped")

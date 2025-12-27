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


def start_scheduler() -> None:
    """
    Start the background scheduler.

    This function is idempotent: calling it multiple times will not
    start multiple schedulers.

    Registers three jobs:
    - update_match_results: Runs every 6 hours
    - update_fixtures: Runs every 12 hours
    - retrain_model: Runs every 2 weeks (14 days)
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
        hours=6,
        id="update_match_results",
        replace_existing=True,
    )

    _scheduler.add_job(
        update_fixtures,
        trigger="interval",
        hours=12,
        id="update_fixtures",
        replace_existing=True,
    )

    _scheduler.add_job(
        retrain_model,
        trigger="interval",
        days=14,  # Every 2 weeks
        id="retrain_model",
        replace_existing=True,
    )

    _scheduler.start()

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

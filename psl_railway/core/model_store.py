"""
Model storage utilities for saving and loading trained models.

Provides functions to persist trained models to disk using joblib.
"""
from pathlib import Path

import joblib

MODEL_PATH = Path("data/models/latest.joblib")


def save_model(model: object) -> None:
    """
    Save a trained model to disk.

    Creates the directory structure if it doesn't exist.

    Args:
        model: Trained model object to save.
    """
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)


def load_model() -> object:
    """
    Load a trained model from disk.

    Returns:
        Loaded model object, or None if model file doesn't exist.
    """
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    return None

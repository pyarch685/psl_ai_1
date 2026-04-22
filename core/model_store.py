"""
Model storage utilities for saving and loading trained models.

Provides functions to persist trained models to disk using joblib.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

import joblib


def _model_path() -> Path:
    storage_root = Path(os.getenv("MODEL_STORAGE_PATH", "data/models"))
    return storage_root / "latest.joblib"


def save_model(model: object) -> None:
    """
    Save a trained model to disk.

    Creates the directory structure if it doesn't exist.

    Args:
        model: Trained model object to save.
    """
    model_path = _model_path()
    model_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file in the same directory, then atomically replace.
    with tempfile.NamedTemporaryFile(
        dir=model_path.parent,
        prefix="latest.",
        suffix=".joblib.tmp",
        delete=False,
    ) as tmp:
        temp_path = Path(tmp.name)

    try:
        joblib.dump(model, temp_path)
        temp_path.replace(model_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def load_model() -> object:
    """
    Load a trained model from disk.

    Returns:
        Loaded model object, or None if model file doesn't exist.
    """
    model_path = _model_path()
    if model_path.exists():
        return joblib.load(model_path)
    return None

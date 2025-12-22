"""
FastAPI server for PSL Soccer Predictor.

Provides REST API endpoints for predictions and model management.
"""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, skip .env loading
    pass

# Import core prediction logic
from core.prediction import (
    ModelArtifacts,
    train_classifier,
    predict_softmax,
    load_history,
    load_fixtures,
    load_all_match_data,
)
from core.model_store import save_model, load_model
from db.engine import get_db_engine

app = FastAPI(
    title="PSL Soccer Predictor API",
    description="API for Premier Soccer League match predictions",
    version="1.0.0"
)

# Enable CORS for web frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load saved model on startup
@app.on_event("startup")
async def load_saved_model():
    """
    Load saved model from disk on application startup.
    
    If a saved model exists, it will be loaded into memory.
    Otherwise, the model will need to be trained via /train endpoint.
    """
    global _model_cache
    
    try:
        saved_model = load_model()
        if saved_model:
            _model_cache = saved_model
            print(f"[api] ✓ Loaded saved model from disk")
            print(f"[api]   Model type: {saved_model.params.get('model', 'Unknown')}")
            print(f"[api]   Teams: {len(saved_model.team_elo)}")
            print(f"[api]   Calibrated: {saved_model.params.get('calibrated', False)}")
        else:
            print("[api] No saved model found. Train a model using /train endpoint")
    except Exception as e:
        print(f"[api] Warning: Failed to load saved model: {e}")
        print("[api] Continuing without saved model...")

# Global model cache
_model_cache: Optional[ModelArtifacts] = None
_model_params = {
    "do_tune": True,
    "do_calib": True,
    "use_nn": True,
    "random_seed": 42
}


# Pydantic models for request/response
class PredictionRequest(BaseModel):
    """Request model for match prediction."""
    home_team: str
    away_team: str


class PredictionResponse(BaseModel):
    """Response model for match prediction."""
    home_team: str
    away_team: str
    probabilities: Dict[str, float]
    predicted_outcome: str
    confidence: float


class FixturePrediction(BaseModel):
    """Model for fixture prediction."""
    date: str
    home_team: str
    away_team: str
    probabilities: Dict[str, float]
    predicted_outcome: str
    confidence: float


class TrainRequest(BaseModel):
    """Request model for model training."""
    do_tune: bool = True
    do_calib: bool = True
    use_nn: bool = True
    random_seed: int = 42


class TrainResponse(BaseModel):
    """Response model for model training."""
    success: bool
    message: str
    model_params: Dict


class UserFeedbackRequest(BaseModel):
    """Request model for user feedback."""
    fixture_id: int
    home_team: str
    away_team: str
    user_prediction: str  # 'home_win', 'draw', or 'away_win'
    user_email: Optional[str] = None


class FeedbackResponse(BaseModel):
    """Response model for user feedback."""
    success: bool
    message: str


@app.get("/")
async def root() -> Dict[str, Any]:
    """
    Root endpoint providing API information.

    Returns:
        Dict containing API message, version, and available endpoints.
    """
    return {
        "message": "PSL Soccer Predictor API",
        "version": "1.0.0",
        "endpoints": {
            "/teams": "Get list of all teams",
            "/predict": "Make a prediction for a match",
            "/fixtures": "Get upcoming fixtures with predictions",
            "/train": "Train/retrain the model",
            "/model/status": "Get current model status"
        }
    }


@app.get("/health")
async def health() -> Dict[str, str]:
    """
    Health check endpoint.

    Checks database connectivity and returns service status.

    Returns:
        Dict with status and database connection state.
    """
    try:
        engine = get_db_engine()
        # Try to connect
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@app.get("/teams")
async def get_teams() -> Dict[str, Any]:
    """
    Get list of all teams from historical data.

    Returns:
        Dict containing list of teams and count.

    Raises:
        HTTPException: If teams cannot be loaded from database.
    """
    try:
        hist = load_history("matches")
        teams = sorted(set(hist["home_team"]).union(hist["away_team"]))
        return {"teams": teams, "count": len(teams)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load teams: {str(e)}"
        )


@app.post("/predict", response_model=PredictionResponse)
async def predict_match(request: PredictionRequest) -> PredictionResponse:
    """
    Make a prediction for a single match.

    Args:
        request: PredictionRequest containing home_team and away_team.

    Returns:
        PredictionResponse with probabilities and predicted outcome.

    Raises:
        HTTPException: If model not trained or prediction fails.
    """
    global _model_cache

    if _model_cache is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Model not trained. Please train the model first "
                "using /train endpoint."
            )
        )

    try:
        probabilities = predict_softmax(
            _model_cache,
            request.home_team,
            request.away_team
        )
        predicted_outcome = max(probabilities.items(), key=lambda x: x[1])[0]
        confidence = probabilities[predicted_outcome]

        return PredictionResponse(
            home_team=request.home_team,
            away_team=request.away_team,
            probabilities=probabilities,
            predicted_outcome=predicted_outcome,
            confidence=confidence
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Prediction failed: {str(e)}"
        )


@app.get("/fixtures")
async def get_fixtures_with_predictions(
    days: int = 14,
    limit: int = 5
) -> Dict[str, Any]:
    """
    Get upcoming fixtures with predictions.

    Args:
        days: Number of days ahead to fetch fixtures (default: 14).
        limit: Maximum number of fixtures to return (default: 5).

    Returns:
        Dict containing list of fixtures with predictions and count.
        Each fixture includes: date, home_team, away_team, venue, time,
        probabilities, predicted_outcome, confidence.

    Raises:
        HTTPException: If model not trained or fixtures cannot be loaded.
    """
    global _model_cache

    if _model_cache is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Model not trained. Please train the model first "
                "using /train endpoint."
            )
        )

    try:
        fixtures = load_fixtures("fixtures")
        fixtures["date"] = pd.to_datetime(fixtures["date"], errors="coerce")

        today = pd.Timestamp.today().normalize()
        end_date = today + pd.Timedelta(days=days)

        # Filter for upcoming fixtures (not completed)
        # Include fixtures that are scheduled, on schedule, or have null/empty status
        # Exclude only completed, postponed, or delayed fixtures
        status_filter = (
            fixtures["status"].isin(["on schedule", "scheduled"]) | 
            fixtures["status"].isna() |
            (fixtures["status"] == "") |
            (~fixtures["status"].isin(["completed", "postponed", "delayed"]))
        )
        upcoming = fixtures[
            (fixtures["date"] >= today) & 
            (fixtures["date"] <= end_date) &
            status_filter
        ].copy()

        # Sort by date and limit to requested number
        upcoming = upcoming.sort_values("date").head(limit)

        if upcoming.empty:
            return {
                "fixtures": [],
                "count": 0,
                "message": "No upcoming fixtures found"
            }

        predictions = []
        for _, row in upcoming.iterrows():
            try:
                probs = predict_softmax(
                    _model_cache,
                    row.home_team,
                    row.away_team
                )
                predicted_outcome = max(probs.items(), key=lambda x: x[1])[0]
                confidence = probs[predicted_outcome]

                # Extract date and time from datetime
                date_obj = row.date if pd.notna(row.date) else None
                if date_obj:
                    # Convert to pandas Timestamp if needed
                    if isinstance(date_obj, pd.Timestamp):
                        date_str = date_obj.strftime("%Y-%m-%d")
                        # Check if time component exists (not midnight or has time info)
                        if date_obj.hour == 0 and date_obj.minute == 0:
                            time_str = "15:00"  # Default match time
                        else:
                            time_str = date_obj.strftime("%H:%M")
                    else:
                        # Fallback for other date types
                        date_str = str(date_obj)[:10]  # First 10 chars (YYYY-MM-DD)
                        time_str = "15:00"
                else:
                    date_str = ""
                    time_str = "15:00"  # Default time

                # Get venue from row
                venue = ""
                try:
                    if "venue" in row.index:
                        venue_val = row.venue
                        if pd.notna(venue_val) and str(venue_val).strip():
                            venue = str(venue_val).strip()
                except (KeyError, AttributeError):
                    pass

                predictions.append({
                    "date": date_str,
                    "time": time_str,
                    "home_team": str(row.home_team),
                    "away_team": str(row.away_team),
                    "venue": venue if venue else "TBD",
                    "probabilities": probs,
                    "predicted_outcome": predicted_outcome,
                    "confidence": float(confidence)
                })
            except Exception as e:
                # Skip fixtures that fail prediction
                print(f"[api] Warning: Failed to predict for {row.home_team} vs {row.away_team}: {e}")
                continue

        return {"fixtures": predictions, "count": len(predictions)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load fixtures: {str(e)}"
        )


@app.post("/train", response_model=TrainResponse)
async def train_model(request: TrainRequest) -> TrainResponse:
    """
    Train or retrain the prediction model.

    Args:
        request: TrainRequest with training parameters.

    Returns:
        TrainResponse with training results and model parameters.

    Raises:
        HTTPException: If insufficient data or training fails.
    """
    global _model_cache, _model_params

    try:
        # Set random seed
        random.seed(request.random_seed)
        np.random.seed(request.random_seed)

        # Load all match data (historical matches + completed fixtures)
        hist = load_all_match_data("matches", "fixtures")

        if len(hist) < 50:
            raise HTTPException(
                status_code=400,
                detail="Insufficient historical data. Need at least 50 matches."
            )

        # Train model
        _model_cache = train_classifier(
            hist,
            do_tune=request.do_tune,
            calibrate=request.do_calib,
            use_nn=request.use_nn
        )

        _model_params = {
            "do_tune": request.do_tune,
            "do_calib": request.do_calib,
            "use_nn": request.use_nn,
            "random_seed": request.random_seed
        }

        # Save model to disk
        try:
            save_model(_model_cache)
            print(f"[api] ✓ Model saved to disk")
        except Exception as e:
            print(f"[api] Warning: Failed to save model to disk: {e}")
            # Continue anyway - model is in memory

        return TrainResponse(
            success=True,
            message=f"Model trained successfully on {len(hist)} matches",
            model_params={
                "model_type": _model_cache.params["model"],
                "calibrated": _model_cache.params["calibrated"],
                "k": _model_cache.params["k"],
                "home_adv": _model_cache.params["home_adv"],
                "window": _model_cache.params["window"],
                "training_matches": len(hist)
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Training failed: {str(e)}"
        )


@app.get("/model/status")
async def get_model_status() -> Dict[str, Any]:
    """
    Get current model status and parameters.

    Returns:
        Dict containing model training status and parameters.
    """
    global _model_cache, _model_params

    if _model_cache is None:
        return {
            "trained": False,
            "message": "Model not trained yet"
        }

    # Check if model file exists on disk
    from core.model_store import MODEL_PATH
    model_on_disk = MODEL_PATH.exists()

    return {
        "trained": True,
        "saved_to_disk": model_on_disk,
        "model_params": {
            "model_type": _model_cache.params["model"],
            "calibrated": _model_cache.params["calibrated"],
            "k": _model_cache.params["k"],
            "home_adv": _model_cache.params["home_adv"],
            "window": _model_cache.params["window"]
        },
        "training_params": _model_params,
        "teams_count": len(_model_cache.team_elo)
    }


@app.get("/content/about")
async def get_about_content() -> Dict[str, str]:
    """
    Get About content from text file.

    Returns:
        Dict containing the about content.
    """
    try:
        about_path = Path("docs/about_soccer_predictor.txt")
        if about_path.exists():
            content = about_path.read_text(encoding="utf-8")
            return {"content": content}
        else:
            raise HTTPException(
                status_code=404,
                detail="About content file not found"
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load about content: {str(e)}"
        )


@app.get("/content/disclaimer")
async def get_disclaimer_content() -> Dict[str, str]:
    """
    Get Disclaimer content from text file.

    Returns:
        Dict containing the disclaimer content.
    """
    try:
        disclaimer_path = Path("docs/virtualsite_disclaimer_notice.txt")
        if disclaimer_path.exists():
            content = disclaimer_path.read_text(encoding="utf-8")
            return {"content": content}
        else:
            raise HTTPException(
                status_code=404,
                detail="Disclaimer content file not found"
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load disclaimer content: {str(e)}"
        )


@app.get("/content/contact")
async def get_contact_content() -> Dict[str, str]:
    """
    Get Contact content from text file.

    Returns:
        Dict containing the contact content.
    """
    try:
        contact_path = Path("docs/virtualsite_contact_details.txt")
        if contact_path.exists():
            content = contact_path.read_text(encoding="utf-8")
            return {"content": content}
        else:
            raise HTTPException(
                status_code=404,
                detail="Contact content file not found"
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load contact content: {str(e)}"
        )


@app.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: UserFeedbackRequest) -> FeedbackResponse:
    """
    Submit user feedback/prediction for a fixture.

    Args:
        request: UserFeedbackRequest containing fixture details and user prediction.

    Returns:
        FeedbackResponse with success status and message.

    Raises:
        HTTPException: If feedback submission fails.
    """
    # Validate user_prediction
    valid_predictions = {"home_win", "draw", "away_win"}
    if request.user_prediction not in valid_predictions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prediction. Must be one of: {', '.join(valid_predictions)}"
        )

    try:
        engine = get_db_engine()
        
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO user_feedback 
                    (fixture_id, home_team, away_team, user_prediction, user_email)
                    VALUES (:fixture_id, :home_team, :away_team, :user_prediction, :user_email)
                """),
                {
                    "fixture_id": request.fixture_id,
                    "home_team": request.home_team,
                    "away_team": request.away_team,
                    "user_prediction": request.user_prediction,
                    "user_email": request.user_email,
                }
            )
        
        return FeedbackResponse(
            success=True,
            message="Feedback submitted successfully"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit feedback: {str(e)}"
        )


if __name__ == "__main__":
    import socket
    import sys
    import uvicorn

    # Allow port to be specified via command line or environment variable
    port = int(os.getenv("API_PORT", 8000))

    # Check if port is already in use
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()

    if result == 0:
        print(f"ERROR: Port {port} is already in use!")
        print(f"Options:")
        print(f"  1. Kill the process using port {port}")
        print(f"  2. Use a different port: API_PORT=8001 python api.py")
        print(f"  3. Or edit api.py to change the default port")
        sys.exit(1)

    print(f"Starting API server on http://0.0.0.0:{port}")
    print(f"API docs available at http://localhost:{port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=port)

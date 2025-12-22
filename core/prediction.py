"""
Core prediction module for PSL Soccer Predictor.

This module contains the prediction functions including:
- Data loading from PostgreSQL
- Feature engineering (Elo ratings, form, rest days)
- Model training and prediction
"""
from __future__ import annotations

import os
import re
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from db.engine import get_db_engine

# ML & utilities
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss

TABLE_NAME_RE = re.compile(r"^\w+$")


def sanitize_table_name(name: str) -> str:
    """
    Sanitize and validate table name to prevent SQL injection.

    Args:
        name: Table name to sanitize.

    Returns:
        Sanitized table name.

    Raises:
        ValueError: If table name contains invalid characters.
    """
    if not TABLE_NAME_RE.match(name):
        raise ValueError("Invalid table name.")
    return name


def load_history(table_name: str = "matches") -> pd.DataFrame:
    """
    Load historical match data from PostgreSQL database.

    Args:
        table_name: Name of the table containing match history.

    Returns:
        DataFrame with columns: date, home_team, away_team,
        home_goals, away_goals, venue (if available).

    Raises:
        RuntimeError: If required columns are missing from table.
    """
    table_name = sanitize_table_name(table_name)
    engine = get_db_engine()
    q = f"""
        SELECT date, home_team, away_team, home_goals, away_goals, venue
        FROM {table_name}
        ORDER BY date
    """
    df = pd.read_sql(q, engine, parse_dates=["date"])
    req = {"date", "home_team", "away_team", "home_goals", "away_goals"}
    missing = req - set(df.columns)
    if missing:
        raise RuntimeError(
            f"History table is missing columns: {sorted(missing)}"
        )
    # Venue is optional, fill with empty string if missing
    if "venue" not in df.columns:
        df["venue"] = ""
    return df


def load_fixtures(table_name: str = "fixtures") -> pd.DataFrame:
    """
    Load fixtures table from PostgreSQL database.

    Args:
        table_name: Name of the table containing fixtures.

    Returns:
        DataFrame with columns: date, home_team, away_team,
        venue, status, home_goals, away_goals (if available).

    Raises:
        RuntimeError: If required columns are missing from table.
    """
    table_name = sanitize_table_name(table_name)
    engine = get_db_engine()
    q = f"""
        SELECT date, home_team, away_team, venue, status, home_goals, away_goals
        FROM {table_name}
        ORDER BY date
    """
    df = pd.read_sql(q, engine, parse_dates=["date"])
    req = {"date", "home_team", "away_team"}
    missing = req - set(df.columns)
    if missing:
        raise RuntimeError(
            f"Fixtures table is missing columns: {sorted(missing)}"
        )
    # Venue and status are optional, fill with defaults if missing
    if "venue" not in df.columns:
        df["venue"] = ""
    if "status" not in df.columns:
        df["status"] = "on schedule"
    # home_goals and away_goals are optional (NULL for upcoming matches)
    if "home_goals" not in df.columns:
        df["home_goals"] = None
    if "away_goals" not in df.columns:
        df["away_goals"] = None
    return df


def load_completed_fixtures(table_name: str = "fixtures") -> pd.DataFrame:
    """
    Load completed fixtures (played matches) from fixtures table.

    Args:
        table_name: Name of the table containing fixtures.

    Returns:
        DataFrame with columns: date, home_team, away_team,
        home_goals, away_goals, venue.
        Only includes fixtures with status='completed' and valid scores.

    Raises:
        RuntimeError: If required columns are missing from table.
    """
    table_name = sanitize_table_name(table_name)
    engine = get_db_engine()
    q = f"""
        SELECT date, home_team, away_team, home_goals, away_goals, venue
        FROM {table_name}
        WHERE status = 'completed'
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
        ORDER BY date
    """
    df = pd.read_sql(q, engine, parse_dates=["date"])
    req = {"date", "home_team", "away_team", "home_goals", "away_goals"}
    missing = req - set(df.columns)
    if missing:
        raise RuntimeError(
            f"Fixtures table is missing columns: {sorted(missing)}"
        )
    # Venue is optional, fill with empty string if missing
    if "venue" not in df.columns:
        df["venue"] = ""
    return df


def load_all_match_data(
    matches_table: str = "matches",
    fixtures_table: str = "fixtures"
) -> pd.DataFrame:
    """
    Load all match data combining historical matches and completed fixtures.

    This function combines:
    - Historical matches from the matches table
    - Completed fixtures (played matches) from the fixtures table

    This ensures predictions are made using the most up-to-date data,
    including recently played fixtures.

    Args:
        matches_table: Name of the table containing historical matches.
        fixtures_table: Name of the table containing fixtures.

    Returns:
        DataFrame with columns: date, home_team, away_team,
        home_goals, away_goals, venue.
        Combined and sorted by date.

    Raises:
        RuntimeError: If required columns are missing from tables.
    """
    # Load historical matches
    hist_matches = load_history(matches_table)
    
    # Load completed fixtures
    try:
        completed_fixtures = load_completed_fixtures(fixtures_table)
    except Exception as e:
        # If fixtures table doesn't exist or has no completed matches,
        # continue with just historical matches
        print(f"[prediction] Warning: Could not load completed fixtures: {e}")
        completed_fixtures = pd.DataFrame(columns=hist_matches.columns)
    
    # Combine both data sources
    if not completed_fixtures.empty:
        # Ensure both DataFrames have the same columns
        common_cols = ["date", "home_team", "away_team", "home_goals", "away_goals", "venue"]
        hist_matches = hist_matches[common_cols]
        completed_fixtures = completed_fixtures[common_cols]
        
        # Combine and remove duplicates (in case a match exists in both tables)
        all_matches = pd.concat([hist_matches, completed_fixtures], ignore_index=True)
        
        # Remove duplicates based on date, teams, and scores
        all_matches = all_matches.drop_duplicates(
            subset=["date", "home_team", "away_team", "home_goals", "away_goals"],
            keep="last"  # Keep fixture version if duplicate (more recent)
        )
        
        # Sort by date
        all_matches = all_matches.sort_values("date").reset_index(drop=True)
    else:
        all_matches = hist_matches
    
    return all_matches


# ---------------- Data & Feature Engineering ----------------
@dataclass
class ModelArtifacts:
    """
    Container for trained model artifacts.

    Attributes:
        pipe: Trained sklearn pipeline (scaler + classifier).
        team_elo: Dictionary mapping team names to Elo ratings.
        team_form: Dictionary mapping team names to recent form.
        params: Dictionary of model parameters (k, home_adv, etc.).
    """
    pipe: object
    team_elo: Dict[str, float]
    team_form: Dict[str, float]
    params: Dict[str, float]


def outcome_label(hg: int, ag: int) -> int:
    """
    Convert match result to outcome label.

    Args:
        hg: Home team goals.
        ag: Away team goals.

    Returns:
        0 if home wins, 1 if draw, 2 if away wins.
    """
    return 0 if hg > ag else (1 if hg == ag else 2)


def build_elo(
    df: pd.DataFrame,
    k: float = 24.0,
    base: float = 1500.0,
    home_adv: float = 70.0
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    Build Elo ratings over time and return feature frame.

    Args:
        df: DataFrame with match results sorted by date.
        k: Elo K-factor (default: 24.0).
        base: Base Elo rating (default: 1500.0).
        home_adv: Home advantage in Elo points (default: 70.0).

    Returns:
        Tuple of (feature DataFrame, final team Elo dictionary).
    """
    teams = pd.unique(df[["home_team", "away_team"]].values.ravel("K"))
    elo = {t: base for t in teams}
    rows = []
    for _, r in df.sort_values("date").iterrows():
        h, a = r.home_team, r.away_team
        Rh, Ra = elo.get(h, base), elo.get(a, base)
        # Elo expectation (home advantage added to home rating)
        Eh = 1.0 / (1.0 + 10 ** (-((Rh + home_adv) - Ra) / 400.0))
        if r.home_goals > r.away_goals:
            Sh, Sa = 1.0, 0.0
        elif r.home_goals == r.away_goals:
            Sh, Sa = 0.5, 0.5
        else:
            Sh, Sa = 0.0, 1.0
        rows.append(
            {
                "date": r.date,
                "home_team": h,
                "away_team": a,
                "elo_home": Rh,
                "elo_away": Ra,
                "elo_diff": (Rh + home_adv) - Ra,
                "label": outcome_label(r.home_goals, r.away_goals),
            }
        )
        elo[h] = Rh + k * (Sh - Eh)
        elo[a] = Ra + k * ((1.0 - Sh) - (1.0 - Eh))
    return pd.DataFrame(rows), elo


def recent_form_features(
    df: pd.DataFrame,
    window: int = 6
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    Compute per-team recent goal-difference rolling mean (form).

    Args:
        df: DataFrame with match results sorted by date.
        window: Rolling window size for form calculation (default: 6).

    Returns:
        Tuple of (feature DataFrame, last known form per team dict).
    """
    g = df.sort_values("date").copy()
    gh = g[["date", "home_team", "home_goals", "away_goals"]].copy().rename(
        columns={"home_team": "team"}
    )
    gh["gd"] = gh["home_goals"] - gh["away_goals"]
    ga = g[["date", "away_team", "home_goals", "away_goals"]].copy().rename(
        columns={"away_team": "team"}
    )
    ga["gd"] = ga["away_goals"] - ga["home_goals"]
    per_team = (
        pd.concat(
            [gh[["date", "team", "gd"]], ga[["date", "team", "gd"]]],
            ignore_index=True
        )
        .sort_values(["team", "date"])
        .reset_index(drop=True)
    )
    per_team["form"] = per_team.groupby("team")["gd"].transform(
        lambda s: s.shift().rolling(window, min_periods=1).mean()
    )
    per_team["rest_days"] = per_team.groupby("team")["date"].transform(
        lambda s: (s - s.shift()).dt.days
    )
    per_team["rest_days"] = per_team["rest_days"].fillna(
        per_team["rest_days"].median()
    )
    g2 = (
        g.merge(
            per_team.rename(
                columns={
                    "team": "home_team",
                    "form": "home_form",
                    "rest_days": "home_rest"
                }
            ),
            on=["date", "home_team"],
            how="left",
        )
        .merge(
            per_team.rename(
                columns={
                    "team": "away_team",
                    "form": "away_form",
                    "rest_days": "away_rest"
                }
            ),
            on=["date", "away_team"],
            how="left",
        )
        .fillna(0.0)
    )
    g2["form_diff"] = g2["home_form"] - g2["away_form"]
    g2["rest_diff"] = g2["home_rest"] - g2["away_rest"]
    last_form = (
        per_team.sort_values("date")
        .groupby("team")["form"]
        .last()
        .fillna(0.0)
        .to_dict()
    )
    return (
        g2[["date", "home_team", "away_team", "form_diff", "rest_diff"]],
        last_form
    )


def tune_elo(history: pd.DataFrame) -> Tuple[float, float]:
    """
    Tune Elo parameters (K-factor and home advantage) via grid search.

    Args:
        history: Historical match data DataFrame.

    Returns:
        Tuple of (best K-factor, best home advantage).
    """
    df = history.copy().sort_values("date")
    if len(df) < 80:
        return 24.0, 70.0
    best = (1e9, 24.0, 70.0)
    for K in (16.0, 20.0, 24.0, 28.0, 32.0):
        for HA in (40.0, 60.0, 70.0, 80.0):
            ef, _ = build_elo(df, k=K, home_adv=HA)
            ff, _ = recent_form_features(df)
            feat = ef.merge(
                ff,
                on=["date", "home_team", "away_team"],
                how="left"
            ).fillna(0.0)
            X = feat[["elo_diff", "form_diff", "rest_diff"]].values
            y = feat["label"].values
            cut = int(0.8 * len(y))
            if (cut < 10 or
                    len(pd.unique(y[:cut])) < 3 or
                    len(pd.unique(y[cut:])) < 3):
                continue
            base = Pipeline([
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(
                    multi_class="multinomial",
                    max_iter=1000,
                    C=2.0
                ))
            ])
            base.fit(X[:cut], y[:cut])
            ll = log_loss(y[cut:], base.predict_proba(X[cut:]))
            if ll < best[0]:
                best = (ll, K, HA)
    return best[1], best[2]


def train_classifier(
    history: pd.DataFrame,
    do_tune: bool = True,
    calibrate: bool = True,
    use_nn: bool = True
) -> ModelArtifacts:
    """
    Train a classifier on Elo+form+rest features.

    Args:
        history: Historical match data DataFrame.
        do_tune: Whether to tune Elo parameters (default: True).
        calibrate: Whether to calibrate probabilities (default: True).
        use_nn: Whether to use neural network (default: True).

    Returns:
        ModelArtifacts containing trained model and parameters.
    """
    df = history.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = (
        df.dropna(subset=["home_team", "away_team", "home_goals", "away_goals"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    k, ha = (tune_elo(df) if do_tune else (24.0, 70.0))
    elo_feat, team_elo = build_elo(df, k=k, home_adv=ha)
    form_feat, last_form = recent_form_features(df, window=6)
    feat = elo_feat.merge(
        form_feat,
        on=["date", "home_team", "away_team"],
        how="left"
    ).fillna(0.0)
    X = feat[["elo_diff", "form_diff", "rest_diff"]].values
    y = feat["label"].values

    if use_nn:
        base_clf = MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation="relu",
            solver="adam",
            alpha=1e-4,
            learning_rate_init=1e-3,
            max_iter=400,
            early_stopping=True,
            n_iter_no_change=20,
            validation_fraction=0.15,
            random_state=42,
        )
    else:
        base_clf = LogisticRegression(
            multi_class="multinomial",
            max_iter=1000,
            C=2.0
        )

    base = Pipeline([("scaler", StandardScaler()), ("clf", base_clf)])

    calibrated_flag = False
    if calibrate and len(df) >= 120 and len(pd.unique(y)) == 3:
        tscv = TimeSeriesSplit(n_splits=4)
        pipe = CalibratedClassifierCV(base, method="isotonic", cv=tscv)
        pipe.fit(X, y)
        calibrated_flag = True
    else:
        pipe = base.fit(X, y)

    return ModelArtifacts(
        pipe=pipe,
        team_elo=team_elo,
        team_form=last_form,
        params={
            "k": k,
            "home_adv": ha,
            "window": 6,
            "calibrated": calibrated_flag,
            "model": "Neural Net (MLP)" if use_nn else "Softmax",
        },
    )


def features_for_pair(
    art: ModelArtifacts,
    home: str,
    away: str
) -> np.ndarray:
    """
    Extract features for a team pair.

    Args:
        art: ModelArtifacts containing team Elo and form data.
        home: Home team name.
        away: Away team name.

    Returns:
        Feature array with shape (1, 3) containing:
        [elo_diff, form_diff, rest_diff].
    """
    eh = art.team_elo.get(home, 1500.0)
    ea = art.team_elo.get(away, 1500.0)
    elo_diff = (eh + art.params["home_adv"]) - ea
    fh = art.team_form.get(home, 0.0)
    fa = art.team_form.get(away, 0.0)
    form_diff = fh - fa
    rest_diff = 0.0
    return np.array([[elo_diff, form_diff, rest_diff]], dtype=float)


def predict_softmax(
    art: ModelArtifacts,
    home: str,
    away: str
) -> Dict[str, float]:
    """
    Predict match outcome probabilities.

    Args:
        art: ModelArtifacts containing trained model.
        home: Home team name.
        away: Away team name.

    Returns:
        Dictionary with probabilities for "Home", "Draw", "Away".
    """
    X = features_for_pair(art, home, away)
    proba = art.pipe.predict_proba(X)[0]
    return {
        "Home": float(proba[0]),
        "Draw": float(proba[1]),
        "Away": float(proba[2])
    }

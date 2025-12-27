"""
CSV import utility for historical match data from seasons files.

Imports data from data/seasons/*.csv files into the matches table.
Handles en dash score format, includes venue, capacity (attendance), and referee.
Excludes match report column.
"""
import logging
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

# Add project root to Python path so db module can be imported
sys.path.insert(0, str(BASE_DIR))

from db.engine import get_db_engine

logger = logging.getLogger(__name__)

SEASONS_DIR = BASE_DIR / "data" / "seasons"
MATCHES_TABLE = "matches"


def parse_score(score_str: str) -> tuple[int, int]:
    """
    Parse score string with en dash format to extract goals.

    Args:
        score_str: Score string in format "X–Y" (en dash) or "X-Y" (hyphen).

    Returns:
        Tuple of (home_goals, away_goals).

    Raises:
        ValueError: If score format is invalid.
    """
    if pd.isna(score_str) or not str(score_str).strip():
        raise ValueError(f"Invalid score: {score_str}")

    score_str = str(score_str).strip()

    # Try en dash first (most common in seasons files)
    if "–" in score_str:
        parts = score_str.split("–")
    elif "-" in score_str:
        parts = score_str.split("-")
    else:
        raise ValueError(f"Invalid score format: {score_str}")

    if len(parts) != 2:
        raise ValueError(f"Invalid score format: {score_str}")

    try:
        home_goals = int(parts[0].strip())
        away_goals = int(parts[1].strip())
        return home_goals, away_goals
    except ValueError as e:
        raise ValueError(f"Invalid score format: {score_str}") from e


def validate_season_data(df: pd.DataFrame) -> bool:
    """
    Validate season CSV data structure and content.

    Args:
        df: DataFrame to validate.

    Returns:
        True if valid.

    Raises:
        ValueError: If required columns are missing or data is invalid.
    """
    required_columns = ["Date", "Home", "Away", "Score"]
    missing = set(required_columns) - set(df.columns)

    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    # Filter out rows with null values in required columns (empty rows)
    df_valid = df[required_columns].dropna()
    
    if len(df_valid) == 0:
        raise ValueError("CSV has no valid rows after filtering nulls")

    # Validate score format on non-null rows only
    invalid_scores = []
    for idx, row in df_valid.iterrows():
        try:
            parse_score(row["Score"])
        except ValueError:
            invalid_scores.append((idx, row["Score"]))

    if invalid_scores:
        raise ValueError(
            f"CSV contains {len(invalid_scores)} invalid scores. "
            f"First invalid: row {invalid_scores[0][0]}, score: {invalid_scores[0][1]}"
        )

    return True


def normalize_season_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize season CSV data to match database schema.

    Args:
        df: Raw DataFrame from CSV.

    Returns:
        Normalized DataFrame with columns: date, home_team, away_team,
        home_goals, away_goals, venue, capacity, referee.
    """
    # Filter out rows with null values in required columns
    required_cols = ["Date", "Home", "Away", "Score"]
    df_clean = df[required_cols].dropna().copy()
    
    if len(df_clean) == 0:
        return pd.DataFrame(columns=["date", "home_team", "away_team", "home_goals", "away_goals", "venue", "capacity", "referee"])

    # Create normalized dataframe
    normalized = pd.DataFrame()

    # Parse date
    normalized["date"] = pd.to_datetime(df_clean["Date"]).dt.date

    # Map team columns
    normalized["home_team"] = df_clean["Home"].astype(str).str.strip()
    normalized["away_team"] = df_clean["Away"].astype(str).str.strip()

    # Parse scores (only on valid rows)
    scores = df_clean["Score"].apply(parse_score)
    normalized["home_goals"] = [s[0] for s in scores]
    normalized["away_goals"] = [s[1] for s in scores]

    # Venue (nullable) - align with cleaned dataframe index
    if "Venue" in df.columns:
        venue_series = df.loc[df_clean.index, "Venue"] if len(df_clean) > 0 else pd.Series()
        normalized["venue"] = venue_series.astype(str).replace("nan", "").str.strip()
        normalized["venue"] = normalized["venue"].replace("", None)
    else:
        normalized["venue"] = None

    # Capacity (Attendance column, nullable)
    if "Attendance" in df.columns:
        # Convert to integer, handling NaN values
        attendance_series = df.loc[df_clean.index, "Attendance"] if len(df_clean) > 0 else pd.Series()
        normalized["capacity"] = pd.to_numeric(attendance_series, errors="coerce")
        normalized["capacity"] = normalized["capacity"].astype("Int64")  # Nullable integer
    else:
        normalized["capacity"] = None

    # Referee (nullable)
    if "Referee" in df.columns:
        referee_series = df.loc[df_clean.index, "Referee"] if len(df_clean) > 0 else pd.Series()
        normalized["referee"] = referee_series.astype(str).replace("nan", "").str.strip()
        normalized["referee"] = normalized["referee"].replace("", None)
    else:
        normalized["referee"] = None

    return normalized


def import_seasons_data(seasons_dir: Path = None) -> None:
    """
    Import all season CSV files into matches table.

    Args:
        seasons_dir: Directory containing season CSV files.
            Defaults to data/seasons/.

    Raises:
        FileNotFoundError: If seasons directory doesn't exist.
        ValueError: If CSV data is invalid.
    """
    if seasons_dir is None:
        seasons_dir = SEASONS_DIR

    if not seasons_dir.exists():
        raise FileNotFoundError(f"Seasons directory not found: {seasons_dir}")

    # Find all CSV files
    csv_files = sorted(seasons_dir.glob("*.csv"))

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {seasons_dir}")

    logger.info(f"[import] Found {len(csv_files)} season files to import")

    # Get database connection
    engine = get_db_engine()

    total_inserted = 0
    total_skipped = 0
    total_errors = 0

    # Process each season file
    for csv_file in csv_files:
        logger.info(f"[import] Processing {csv_file.name}...")

        try:
            # Read CSV file
            df = pd.read_csv(csv_file)
            logger.info(f"[import] Loaded {len(df)} rows from {csv_file.name}")

            # Validate data
            validate_season_data(df)
            logger.info(f"[import] Validation passed for {csv_file.name}")

            # Normalize data
            normalized_df = normalize_season_data(df)
            logger.info(f"[import] Normalized {len(normalized_df)} rows")

            # Import to database
            file_inserted = 0
            file_skipped = 0
            file_errors = 0

            with engine.begin() as conn:
                for idx, row in normalized_df.iterrows():
                    try:
                        # Check if record already exists
                        exists = conn.execute(
                            text(
                                f"""
                                SELECT 1 FROM {MATCHES_TABLE}
                                WHERE date = :date
                                  AND home_team = :home_team
                                  AND away_team = :away_team
                                """
                            ),
                            {
                                "date": row["date"],
                                "home_team": row["home_team"],
                                "away_team": row["away_team"],
                            },
                        ).fetchone()

                        if exists:
                            file_skipped += 1
                            continue

                        # Insert record
                        conn.execute(
                            text(
                                f"""
                                INSERT INTO {MATCHES_TABLE}
                                (date, home_team, away_team, home_goals, away_goals, 
                                 venue, capacity, referee)
                                VALUES
                                (:date, :home_team, :away_team, :home_goals, :away_goals,
                                 :venue, :capacity, :referee)
                                """
                            ),
                            {
                                "date": row["date"],
                                "home_team": row["home_team"],
                                "away_team": row["away_team"],
                                "home_goals": int(row["home_goals"]),
                                "away_goals": int(row["away_goals"]),
                                "venue": row.get("venue"),
                                "capacity": (
                                    int(row["capacity"])
                                    if pd.notna(row.get("capacity"))
                                    else None
                                ),
                                "referee": row.get("referee"),
                            },
                        )
                        file_inserted += 1

                        # Progress feedback every 50 rows
                        if (idx + 1) % 50 == 0:
                            logger.debug(
                                f"[import] {csv_file.name}: Processed {idx + 1}/{len(normalized_df)} rows"
                            )

                    except Exception as e:
                        file_errors += 1
                        logger.warning(
                            f"[import] Failed to import row {idx + 1} from {csv_file.name}: {e}"
                        )
                        continue

            total_inserted += file_inserted
            total_skipped += file_skipped
            total_errors += file_errors

            logger.info(
                f"[import] {csv_file.name}: "
                f"{file_inserted} inserted, {file_skipped} skipped, "
                f"{file_errors} errors"
            )

        except Exception as e:
            logger.error(
                f"[import] Failed to process {csv_file.name}: {e}",
                exc_info=True,
            )
            total_errors += len(df) if "df" in locals() else 0
            continue

    logger.info(
        f"[import] Import complete: "
        f"{total_inserted} inserted, {total_skipped} skipped, "
        f"{total_errors} errors across {len(csv_files)} files"
    )
    print(
        f"[import] Imported {total_inserted} matches "
        f"({total_skipped} duplicates skipped, {total_errors} errors)"
    )


def import_csv_to_matches(csv_path: Path = None) -> None:
    """
    Import single CSV file into matches table (legacy function for compatibility).

    Args:
        csv_path: Path to CSV file. If None, imports all season files.

    Raises:
        FileNotFoundError: If CSV file doesn't exist.
        ValueError: If CSV data is invalid.
    """
    if csv_path is None:
        # Default to importing all seasons
        import_seasons_data()
        return

    # Single file import (for backward compatibility)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    logger.info(f"[import] Reading CSV file: {csv_path}")

    try:
        df = pd.read_csv(csv_path)

        # Check if it's a season file format
        if "Date" in df.columns and "Home" in df.columns and "Score" in df.columns:
            # Season file format
            validate_season_data(df)
            normalized_df = normalize_season_data(df)
        else:
            # Legacy format (psl_final.csv)
            # Map legacy columns if needed
            if "date" in df.columns:
                normalized_df = df.copy()
                normalized_df["date"] = pd.to_datetime(normalized_df["date"]).dt.date
                normalized_df["capacity"] = None
                normalized_df["referee"] = None
            else:
                raise ValueError("Unknown CSV format")

        # Import to database
        engine = get_db_engine()
        inserted_count = 0
        skipped_count = 0
        error_count = 0

        with engine.begin() as conn:
            for idx, row in normalized_df.iterrows():
                try:
                    exists = conn.execute(
                        text(
                            f"""
                            SELECT 1 FROM {MATCHES_TABLE}
                            WHERE date = :date
                              AND home_team = :home_team
                              AND away_team = :away_team
                            """
                        ),
                        {
                            "date": row["date"],
                            "home_team": row["home_team"],
                            "away_team": row["away_team"],
                        },
                    ).fetchone()

                    if exists:
                        skipped_count += 1
                        continue

                    conn.execute(
                        text(
                            f"""
                            INSERT INTO {MATCHES_TABLE}
                            (date, home_team, away_team, home_goals, away_goals,
                             venue, capacity, referee)
                            VALUES
                            (:date, :home_team, :away_team, :home_goals, :away_goals,
                             :venue, :capacity, :referee)
                            """
                        ),
                        {
                            "date": row["date"],
                            "home_team": row["home_team"],
                            "away_team": row["away_team"],
                            "home_goals": int(row["home_goals"]),
                            "away_goals": int(row["away_goals"]),
                            "venue": row.get("venue"),
                            "capacity": (
                                int(row["capacity"])
                                if pd.notna(row.get("capacity"))
                                else None
                            ),
                            "referee": row.get("referee"),
                        },
                    )
                    inserted_count += 1

                except Exception as e:
                    error_count += 1
                    logger.warning(f"[import] Failed to import row {idx + 1}: {e}")
                    continue

        logger.info(
            f"[import] Import complete: "
            f"{inserted_count} inserted, {skipped_count} skipped, "
            f"{error_count} errors"
        )
        print(
            f"[import] Imported {inserted_count} matches "
            f"({skipped_count} duplicates skipped)"
        )

    except Exception as e:
        logger.error(f"[import] CSV import failed: {e}", exc_info=True)
        raise


# -------------------------------------------------------------------
# SCRIPT ENTRY POINT
# -------------------------------------------------------------------

if __name__ == "__main__":
    # Configure logging for manual execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Import all season files by default
    import_seasons_data()

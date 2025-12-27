# Database Setup Guide

This directory contains scripts for setting up and managing the PSL AI database schema.

## Files

- `engine.py` - Database connection management
- `create_schema.py` - Unified schema creation (all tables)
- `create_predictions_table.py` - Predictions table creation (legacy, use create_schema.py)
- `import_csv.py` - CSV import utility for historical match data

## Quick Start

### 1. Create All Tables

```bash
python db/create_schema.py
```

This creates all three tables:
- `matches` - Historical match results
- `fixtures` - Upcoming matches
- `predictions` - ML model predictions

### 2. Import Historical Data (Optional)

```bash
python db/import_csv.py
```

This imports data from `data/psl_final.csv` into the `matches` table.

## Table Schemas

### matches
- `id` SERIAL PRIMARY KEY
- `date` DATE NOT NULL
- `home_team` TEXT NOT NULL
- `away_team` TEXT NOT NULL
- `home_goals` INTEGER NOT NULL
- `away_goals` INTEGER NOT NULL
- `venue` TEXT (nullable)
- `created_at` TIMESTAMP DEFAULT NOW()
- `updated_at` TIMESTAMP DEFAULT NOW()
- UNIQUE (date, home_team, away_team)

### fixtures
- `id` SERIAL PRIMARY KEY
- `date` DATE NOT NULL
- `home_team` TEXT NOT NULL
- `away_team` TEXT NOT NULL
- `venue` TEXT (nullable)
- `status` TEXT NOT NULL DEFAULT 'on schedule'
- `created_at` TIMESTAMP DEFAULT NOW()
- `updated_at` TIMESTAMP DEFAULT NOW()
- UNIQUE (date, home_team, away_team)

### predictions
- `id` SERIAL PRIMARY KEY
- `match_date` DATE NOT NULL
- `home_team` TEXT NOT NULL
- `away_team` TEXT NOT NULL
- `home_win_prob` DOUBLE PRECISION NOT NULL
- `draw_prob` DOUBLE PRECISION NOT NULL
- `away_win_prob` DOUBLE PRECISION NOT NULL
- `predicted_outcome` TEXT
- `confidence` DOUBLE PRECISION
- `model_version` TEXT NOT NULL
- `created_at` TIMESTAMP DEFAULT NOW()
- UNIQUE (match_date, home_team, away_team)

## Environment Variables

Ensure these are set in `.env`:
- `DATABASE_URL` OR
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`

## Notes

- All scripts are idempotent (safe to run multiple times)
- Duplicate prevention is handled by UNIQUE constraints
- Indexes are created automatically for performance


1→# Agent Guide
2→
3→## Setup
4→```bash
5→python3 -m venv venv && source venv/bin/activate  # venv/ per .gitignore
6→pip install -r requirements.txt
7→cd web/vuvuzela-vibes-predictor && npm install && cd ../..
8→```
9→
10→## Commands
11→- **Build**: No build step (Python runtime, Vite builds on dev server start)
12→- **Lint**: Not configured
13→- **Test**: Not configured
14→- **Dev server**: `./start_app.sh` (backend on :8000, frontend on :8080) or separately: `python3 main.py` and `./start_frontend.sh`
15→
16→## Tech Stack
17→**Backend**: FastAPI + Uvicorn, SQLAlchemy, PostgreSQL, scikit-learn, pandas, BeautifulSoup4, APScheduler  
18→**Frontend**: React 18 + TypeScript, Vite, shadcn/ui, Tailwind CSS
19→
20→## Architecture
21→- `app/` - FastAPI routes
22→- `core/` - ML prediction logic (Elo, features, models)
23→- `db/` - Database schema, engine, imports
24→- `jobs/` - Background scheduler for scraping
25→- `web/vuvuzela-vibes-predictor/` - React frontend
26→- `data/` - CSV datasets and trained models
27→
28→## Style
29→Python: Type hints, docstrings on modules/functions, `from __future__ import annotations`

## Cursor Cloud specific instructions

### Broken git submodule
`web/vuvuzela-vibes-predictor` is tracked as a git submodule (mode 160000) but `.gitmodules` is missing, so `git submodule update --init` will not work. The update script copies frontend source from `psl_railway/web/vuvuzela-vibes-predictor/` instead. Two files (`src/lib/utils.ts` and `src/lib/api.ts`) are not present in the psl_railway copy but are imported by many components; the update script creates them if missing.

### PostgreSQL
The backend requires PostgreSQL. Install via `apt-get install postgresql`, start with `sudo pg_ctlcluster <version> main start` or `sudo service postgresql start`, then create user/db:
```
sudo -u postgres psql -c "CREATE USER psl_user WITH PASSWORD 'psl_pass';"
sudo -u postgres psql -c "CREATE DATABASE psl_db OWNER psl_user;"
```

### .env file
Create `/workspace/.env` with at minimum:
```
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=psl_db
DB_USER=psl_user
DB_PASSWORD=psl_pass
JWT_SECRET_KEY=dev-secret-key-for-local-development
DISABLE_EMAIL=true
```

### Database schema & seed data
After PostgreSQL is running, create tables and import historical match data:
```bash
source venv/bin/activate
python db/create_schema.py
python db/import_csv.py
```

### Running services
- **Backend**: `source venv/bin/activate && python3 main.py` (port 8000). Verify: `curl http://localhost:8000/health`
- **Frontend**: `cd web/vuvuzela-vibes-predictor && npm run dev` (port 8080)
- The backend loads a pre-trained ML model from `data/models/latest.joblib` on startup. No manual training step needed.
- Lint/test are not configured for this project (see Commands section above).
30→
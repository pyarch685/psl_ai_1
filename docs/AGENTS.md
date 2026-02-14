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
30→
# MongoDBHack Monorepo

This repo contains the frontend (Vite/React) and backend (FastAPI) apps.

## Structure
- `apps/web` — React/Vite frontend
- `apps/api` — FastAPI backend

## Local setup

### Frontend
```bash
cd apps/web
npm install
cp .env.example .env
npm run dev
```

### Backend
```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn main:app --reload --port 8000
```

SQLite is used by default for local smoke tests; configure `DATABASE_URL` for Postgres if you need full functionality.

### Run both (root)
```bash
cd /Users/severinspagnola/Desktop/MongoDBHack
npm install
npm run dev
```

> Note: `npm run dev` uses your active Python environment. Activate the backend venv first.

## Local URLs
- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Health check: `http://localhost:8000/api/health`

## Dev API wiring
The frontend uses a Vite proxy to forward `/api/*` to the backend at `http://localhost:8000`.
If you need to override it, set `VITE_API_BASE_URL` in `apps/web/.env`.

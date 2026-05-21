# FinWise Accounting

Isolated rebuild workspace for the FinWise monthly bookkeeping agency workflow.
This app is intentionally contained under `finwise-accounting/` and does not
modify the legacy root `backend/` or `frontend/` applications.

## Backend

```bash
cd backend
python -m pytest -q
uvicorn app.main:app --reload
```

The FastAPI backend starts with a `/health` endpoint and SQLite defaults for
local development.

## Frontend

```bash
cd frontend
npm install
npm run dev
npm run build
```

The Vue 3 frontend runs on Vite port `5174` and currently contains the minimal
root shell for the rebuild.

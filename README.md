# Blue Query (Frontend + Backend)

This workspace now contains:
- Frontend: Next.js app (root folder)
- Backend: FastAPI app in `backend/` (cloned from `BlueQuery-backend`)

## Run Backend

1. Create a Python environment in `backend/`.
2. Install backend dependencies.
3. Set env vars:
   - `GEMINI_API_KEY`
   - `ARGO_DB_PATH` (default already points to `backend/database/argo_floats_new.db`)
4. Start API:

```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Run Frontend

1. Set `BACKEND_URL` in `.env.local` (or use `.env.example`):
   - `BACKEND_URL=http://127.0.0.1:8000`
2. Start frontend:

```bash
npm run dev
```

Then open landing page and click `Explore FloatChat`.

# Vox Magistri Frontend Foundation

This folder contains a React + TypeScript + Vite foundation that is already wired
to the FastAPI backend in this repository.

## What is wired

- Session bootstrapping via `POST /api/v1/sessions`
- Message list bootstrapping via `GET /api/v1/sessions/{id}/messages`
- Real-time events via `WS /api/v1/ws/sessions/{id}`
- Queue status via `GET /api/v1/intel/status` and WS `status` events

## Environment

Copy `.env.example` to `.env` and adjust if needed:

```bash
cp .env.example .env
```

Defaults:

- `VITE_API_BASE_URL=http://127.0.0.1:5000`
- `VITE_API_TOKEN=dev`

## Run locally

From the repo root:

1. Start backend: `./venv-dnd-server/bin/python -m app.main --debug`
2. Start frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Foundation structure

- `src/lib/config.ts`: API URL/token and WS URL derivation
- `src/lib/api.ts`: typed REST calls
- `src/lib/ws.ts`: typed WS connector + event forwarding
- `src/types.ts`: shared client-side contract types
- `src/App.tsx`: first chat shell and state wiring

This is intentionally a foundation, not a final UX. Next iterations can split
state into hooks/stores, add retries, and layer richer game-specific UI flows.

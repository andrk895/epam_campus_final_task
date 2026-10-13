# Project Hub: web UI

A React + TypeScript single-page app (built with Vite) for the Project Management API.

## Run

```bash
npm install
npm run dev          # http://localhost:5173
```

The backend must be running on `http://localhost:8000` (`uv run uvicorn app.main:app --reload`).
Set `API_TARGET=http://host:port` to point at a different backend.

## How it talks to the backend

The browser only talks to the Vite dev server. Vite forwards every `/api/*` request to the backend with
the `/api` prefix removed (`/api/projects` → `http://localhost:8000/projects`). Because of this, the
backend doesn't need CORS during development.

The JWT from `POST /login` is kept in `localStorage` and sent as `Authorization: Bearer …`. The app logs
out when the token expires (1 hour) or the backend answers `401`.

## Feature detection

The app reads the backend's `/openapi.json` every 30 seconds. While an endpoint doesn't exist yet, the
matching UI shows which task in `specification.md` adds it. The **Backend progress** page lists all
required endpoints and whether each is available.

## Layout

| File | Purpose |
|------|---------|
| `src/api.ts` | HTTP client, response normalization, endpoint catalogue |
| `src/auth.tsx` | Session (token) handling, login/register/logout |
| `src/apiStatus.tsx` | Which endpoints the backend currently has |
| `src/pages/` | Login, project list, project detail, backend progress |
| `src/components.tsx` | Small shared UI pieces and formatters |

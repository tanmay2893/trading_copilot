# Run the app with Docker

This folder contains everything you need to start the **backtester web UI** and **API** in two containers. After startup, open the site at **http://localhost:3000**. The API (including WebSockets) is exposed at **http://localhost:6700**.

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) **and** [Docker Compose](https://docs.docker.com/compose/install/) (Compose V2 is included with Docker Desktop).

## Quick start

From the **repository root** (parent of this `docker` folder):

```bash
docker compose -f docker/docker-compose.yml up --build
```

Or from inside `docker/`:

```bash
cd docker
docker compose up --build
```

When the logs show the frontend listening, visit **http://localhost:3000** in your browser.

- Stop: `Ctrl+C`, or in another terminal:  
  `docker compose -f docker/docker-compose.yml down` (from repo root).

## API keys (LLM)

The chat agent needs at least one provider key (OpenAI, Anthropic, or DeepSeek). Choose one approach:

1. **`.env` in the repo root** (same directory as `pyproject.toml`) with:
   - `OPENAI_API_KEY=...`
   - `ANTHROPIC_API_KEY=...`
   - `DEEPSEEK_API_KEY=...`  
   Compose loads this file into the **backend** container automatically if the file exists.

2. **Environment variables when starting Compose** (values are passed to the backend):
   ```bash
   export OPENAI_API_KEY=sk-...
   docker compose -f docker/docker-compose.yml up --build
   ```

You can still enter keys in the app’s settings UI; those are stored in the backend process (memory) and are lost when the container restarts unless you use env vars or `.env`.

## Ports

| Service  | Port | URL                    |
|----------|------|------------------------|
| Frontend | 3000 | http://localhost:3000  |
| Backend  | 6700 | http://localhost:6700  |

If something else already uses port 3000 or 6700, edit the `ports:` mappings in `docker-compose.yml` (e.g. `"3080:3000"` for the UI). If you change the **published** API port, rebuild the frontend with the REST base URL (**must include `/api`** — that is where FastAPI mounts the router):

```bash
NEXT_PUBLIC_API_URL=http://localhost:NEW_PORT/api docker compose -f docker/docker-compose.yml up --build
```

(`NEXT_PUBLIC_API_URL` is baked in at **image build** time. The UI also normalizes bare `http://host:port` to add `/api` on rebuild.)

## Data persistence

Session files and cache are written **inside the backend container** under `/root/.backtester` by default. Removing the container removes that data. For experiments, that is usually enough. To persist sessions, add a volume in `docker-compose.yml` under `backend`, for example:

```yaml
volumes:
  - backtester_data:/root/.backtester
```

and at the bottom of the file:

```yaml
volumes:
  backtester_data:
```

## Troubleshooting

- **Blank API errors in the browser**  
  Confirm the backend is healthy: open http://localhost:6700/api/health — you should see `{"status":"ok"}`.

- **404 on `http://localhost:6700/sessions` or `/settings/llm-keys`**  
  Those paths must be under **`/api`** (e.g. `/api/sessions`). Rebuild the frontend image (`docker compose up --build`) so it uses `NEXT_PUBLIC_API_URL=.../api`, or rely on the latest `frontend/lib/api.ts` which adds `/api` when the env URL is a bare `http://host:port`.

- **Frontend build fails**  
  Run `npm ci` and `npm run build` locally in `frontend/` to see detailed errors.

- **`dockerDesktopLinuxEngine` / “The system cannot find the file specified” (Windows)**  
  Docker Desktop is not running or the engine has not finished starting. Open **Docker Desktop**, wait until it says **Docker Engine is running**, then run `docker info` in a terminal. If that works, retry `docker compose up --build`.

- **Windows / WSL**  
  Use Docker Desktop with WSL2 integration enabled; run the same `docker compose` commands from your preferred shell.

## Files in this folder

| File                 | Role                                      |
|----------------------|-------------------------------------------|
| `docker-compose.yml` | Runs `frontend` + `backend` together      |
| `Dockerfile.backend` | Python image, FastAPI on port 6700        |
| `Dockerfile.frontend`| Next.js production (standalone) on 3000   |

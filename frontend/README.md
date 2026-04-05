# Backtester UI

## Running locally

1. **Start the backend** (venv or conda with project deps installed, e.g. `pip install -e .` from repo root):
   ```bash
   cd ..   # project root (parent of frontend/)
   uvicorn backtester.api.server:app --reload --port 6700
   ```
   Port **6700** must match `frontend/next.config.ts` dev rewrites.

2. **Start the frontend** (from this folder):
   ```bash
   npm run dev
   ```

3. **Open** [http://localhost:3070](http://localhost:3070)

Next dev runs on **port 3070** (`package.json`). `/api` is rewritten to the backend. WebSockets connect directly to the API port (see `.env.local` / `frontend/.env.example`).

## Using the proxy (e.g. for ngrok)

The proxy defaults to **3080** (`proxy.js`: Next on **3070**, backend on **6700**).

- Terminal 1: `npm run dev` (Next on 3070)
- Terminal 2: `npm run dev:proxy` (proxy on 3080, or set `PROXY_PORT`)
- Open **http://localhost:3080** or run `ngrok http 3080`

The proxy forwards pages to Next (3068) and `/api`, `/ws` to the backend (6800).

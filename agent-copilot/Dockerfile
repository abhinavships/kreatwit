# Kreatwit: site, app and API in one image. Build context: agent-copilot/ (the app reads ../skills and ../dataset).
# Run ONE instance with a persistent volume at /data: each account's DuckDB file lives there, and chat state is in-process.
# The UI is a static export served by the API, so it calls the API on its own origin (empty NEXT_PUBLIC_API_BASE).
FROM node:24-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN NEXT_PUBLIC_API_BASE= NEXT_TELEMETRY_DISABLED=1 npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-install-project

# Dataset (MIT, FlytBase), pinned to a commit. Only sample-data is served.
ADD https://github.com/FlytBaseAILabs/flytbase-ahc-swe-asset-intelligence-dataset/archive/009e2b596782150f420021f9472ab37e3a2953ee.tar.gz /tmp/ds.tgz
RUN mkdir -p /app/dataset && tar -xzf /tmp/ds.tgz -C /app/dataset --strip-components=1 --wildcards '*/sample-data' && rm /tmp/ds.tgz

COPY skills /app/skills
COPY --from=ui /ui/out /app/frontend/out
COPY backend/src ./src
RUN uv sync --frozen
# full-text search extension baked in: workspace connections cannot download extensions (external access is off)
RUN uv run --no-sync python -c "import duckdb; duckdb.connect().execute('INSTALL fts')"

# Everything written at runtime lives on the volume: the template database, one folder per account under /data/ws,
# uploads per account under /data/uploads, usage counters, TTS cache.
ENV DATA_DIR=/app/dataset/sample-data DB_PATH=/data/kreatwit.duckdb PORT=8000
RUN mkdir -p /data && ln -s /data/uploads uploads && ln -s /data/tts_cache .tts_cache
VOLUME /data
EXPOSE 8000

# First boot builds the template database from the sample dataset (a few minutes); new accounts start from a copy.
# Refuses to start without sign-in configured: a public deployment must never run with workspaces off.
CMD ["sh", "-c", ": \"${AUTH_SECRET:?set AUTH_SECRET (openssl rand -hex 32)}\" \"${SUPABASE_URL:?set SUPABASE_URL}\" \"${SUPABASE_ANON_KEY:?set SUPABASE_ANON_KEY}\" && mkdir -p /data/uploads /data/tts_cache && { [ -f \"$DB_PATH\" ] || uv run --no-sync python -m kreatwit.substrate.ingest; } && exec uv run --no-sync uvicorn kreatwit.api.app:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips \"*\""]

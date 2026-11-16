# WellOps backend. Build context: agent-copilot/ (the app reads ../skills and ../dataset relative to backend/).
# Run ONE instance with a persistent volume at /data: DuckDB is single-writer and chat state is in-process.
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

# Everything written at runtime lives on the volume: database, answer cache (next to the db), uploads, TTS cache.
ENV DATA_DIR=/app/dataset/sample-data DB_PATH=/data/wellops.duckdb PORT=8000
RUN mkdir -p /data && ln -s /data/uploads uploads && ln -s /data/tts_cache .tts_cache
VOLUME /data
EXPOSE 8000

# First boot builds the database from the dataset (~1 min); later boots reuse it, keeping corrections and chats.
# Refuses to start without AUTH_SECRET: a public deployment must never run with sign-in off.
CMD ["sh", "-c", ": \"${AUTH_SECRET:?set AUTH_SECRET (openssl rand -hex 32)}\" && mkdir -p /data/uploads /data/tts_cache && { [ -f \"$DB_PATH\" ] || uv run --no-sync python -m wellops.substrate.ingest; } && exec uv run --no-sync uvicorn wellops.api.app:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips \"*\""]

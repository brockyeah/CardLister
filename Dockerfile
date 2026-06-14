# Multi-stage build: build frontend with Node, then run it with Python.

# --- Stage 1: build frontend ---
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
# package-lock.json may not exist on first install; fall back to npm install in that case.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend + bundled static frontend ---
FROM python:3.11-slim

# System deps for httpx + lxml-style parsing (we use stdlib html.parser, but keep build essentials available).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend from stage 1 into the location FastAPI mounts as static
COPY --from=frontend-build /app/frontend/dist ./backend/static

# Default DB path; on Railway, override with DB_PATH=/data/cardlister.db (volume mount)
ENV DB_PATH=/data/cardlister.db

# Railway provides $PORT — fall back to 8000 for local docker run
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]

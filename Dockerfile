# Two stages. Node builds the frontend and is then thrown away; the runtime
# carries Python, ffmpeg and fonts, and nothing that was only needed to compile.

FROM node:22-slim AS web
WORKDIR /build
# Dependencies are installed from the lockfile alone, so editing a component
# does not invalidate the install layer.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build


# Dependencies are resolved here and only the finished environment is copied
# forward. Installing them in the runtime leaves uv itself and its download
# cache behind, which measured 55MB and 288MB of an image that needs neither.
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1
RUN uv sync --locked --no-dev --no-install-project


FROM python:3.12-slim AS runtime

# ffmpeg does the rendering. fontconfig and a font package matter as much: the
# app lists the faces it can draw with by asking fontconfig, and an image
# without fonts offers an empty list and refuses to render any text at all.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation2 \
        fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

WORKDIR /app

COPY --from=deps /opt/venv /opt/venv

COPY core/ ./core/
COPY api/ ./api/
COPY overlay.py ./
COPY --from=web /build/dist ./web/dist

# Uploads, renders and cached frames live here. Mount a volume over it or the
# work disappears with the container.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8787

EXPOSE 8787

# Renders are long, so the check has to be something that answers while one is
# running. The presets endpoint touches no disk and spawns nothing.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/presets', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]

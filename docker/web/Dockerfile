FROM node:22-alpine AS ui-build

WORKDIR /build/webui
COPY webui/package.json webui/package-lock.json webui/vite.config.js webui/index.html ./
COPY webui/src ./src
RUN npm ci --no-audit --no-fund \
    && npm run build

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MIKROCLEAR_WEB_STATIC_DIR=/app/static

RUN groupadd --gid 10001 mikroclear \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin mikroclear

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

COPY --from=ui-build /build/webui/dist /app/static

RUN mkdir -p /var/lib/mikroclear /tmp/mikroclear \
    && chown -R mikroclear:mikroclear /var/lib/mikroclear /tmp/mikroclear

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()" || exit 1

CMD ["mikroclear-web"]

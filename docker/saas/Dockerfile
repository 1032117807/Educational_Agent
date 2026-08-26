FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Native PDF extraction remains available; enable PaddleOCR or a remote vision
# OCR provider explicitly when deploying a scanned-document workload.
ENV LEARNING_AI_OCR_ENABLED=false

# Keep a PostgreSQL 16 client in the release image because the Compose database
# is pgvector/pgvector:pg16.  A newer dump client can emit restore commands an
# older server cannot parse, so the client major must match the server major.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $VERSION_CODENAME-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.saas.txt ./
# Keep transient registry failures from making an otherwise reproducible
# release build fail on the first slow package download.
RUN pip install --no-cache-dir --retries 5 --timeout 120 -r requirements.saas.txt
# Browser screenshots use a headless Chromium with no host browser access.
RUN playwright install --with-deps chromium

COPY pyproject.toml README.md ./
COPY app ./app
COPY ai ./ai
COPY server ./server
COPY skills ./skills
# Keep migration revisions fresh when a new release adds a database change.
ARG MIGRATIONS_CACHE=20260820-task-knowledge-v1
COPY migrations ./migrations
# Re-copy the revisions directory as its own cache key so newly added
# migrations are included in every release image.
COPY migrations/versions ./migrations/versions
COPY scripts ./scripts
COPY alembic.ini ./

RUN pip install --no-cache-dir --no-deps .

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]

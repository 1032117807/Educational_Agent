FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.saas.txt ./
RUN pip install --no-cache-dir -r requirements.saas.txt

COPY pyproject.toml README.md ./
COPY app ./app
COPY ai ./ai
COPY server ./server
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

RUN pip install --no-cache-dir --no-deps .

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# OpenCV, pulled by the local CPU PaddleOCR fallback, needs these runtime
# libraries even though the service has no graphical UI.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.saas.txt ./
RUN pip install --no-cache-dir -r requirements.saas.txt

COPY pyproject.toml README.md ./
COPY app ./app
COPY ai ./ai
COPY server ./server
COPY skills ./skills
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

RUN pip install --no-cache-dir --no-deps .

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]

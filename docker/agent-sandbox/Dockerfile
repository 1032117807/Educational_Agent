FROM python:3.11-slim

RUN useradd --create-home --uid 10001 sandbox
WORKDIR /workspace
USER sandbox

ENTRYPOINT ["python"]
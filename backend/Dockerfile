# One image for the kernel API and the mock connectors; Compose picks the command.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/src backend/src
RUN pip install --no-cache-dir ./backend
COPY packs packs
COPY seed seed
COPY backend/migrations backend/migrations
ENV AOS_PACKS_DIR=/app/packs AOS_ORG_FILE=/app/seed/org.yaml
EXPOSE 8000
CMD ["uvicorn", "aos.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

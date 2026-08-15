# Stage 1: build the frontend SPA
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: assemble the backend + static assets
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends tzdata libgl1 libglib2.0-0 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
RUN mkdir -p /app/data

COPY --from=frontend-build /app/frontend/dist /app/static

EXPOSE 8000

ENV FRONTEND_DIST=/app/static

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

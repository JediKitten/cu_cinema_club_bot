# Многоступенчатая сборка: Node нужен только чтобы собрать Mini App, в рантайм
# он не попадает. Хосту не приходится ставить ни Node, ни Python 3.12.

FROM node:20-alpine AS frontend
WORKDIR /build
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci --silent
COPY miniapp/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIR=/app/frontend

WORKDIR /app/backend

# Зависимости отдельным слоем: пересобираются только при изменении requirements,
# а не на каждую правку кода.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend

# Приложение не должно работать от root даже внутри контейнера.
RUN useradd --system --uid 10001 cinema && chown -R cinema:cinema /app
USER cinema

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]

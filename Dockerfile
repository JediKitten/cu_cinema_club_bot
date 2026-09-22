# Многоступенчатая сборка: Node нужен только чтобы собрать Mini App, в рантайм
# он не попадает. Хосту не приходится ставить ни Node, ни Python 3.12.

FROM node:20-alpine AS frontend
WORKDIR /build
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci --silent
COPY miniapp/ ./
# Коммит, из которого собрано. Попадает и в Mini App, и в /health: так
# приложение видит, что сервер уже новее, а выкат — что приехало нужное.
# Объявлен здесь, а не выше: смена ARG сбивает кэш всех RUN после него.
ARG GIT_SHA=dev
RUN VITE_APP_VERSION=$GIT_SHA npm run build


# Debian закреплён явно: pg_dump из его репозитория должен быть не старше
# сервера базы (postgres:16). В trixie — 17-й, он снимает дампы и с 16-го;
# плавающий тег однажды мог бы переехать на дистрибутив со старым клиентом.
FROM python:3.12-slim-trixie AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIR=/app/frontend

# pg_dump — для ночной копии базы, которую снимает бот.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Зависимости отдельным слоем: пересобираются только при изменении requirements,
# а не на каждую правку кода.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend

# Приложение не должно работать от root даже внутри контейнера.
# Каталог копий создаётся заранее и отдаётся пользователю приложения: пустой
# том Docker при первом подключении наследует владельца отсюда, иначе он
# достался бы root и бот не смог бы в него писать.
RUN useradd --system --uid 10001 cinema \
    && mkdir -p /backups \
    && chown -R cinema:cinema /app /backups
USER cinema

# Версия — последним слоем: она меняется с каждым коммитом, и объявленная
# раньше заставляла бы пересобирать apt и pip на каждом выкате.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]

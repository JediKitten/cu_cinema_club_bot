from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_config

# Сколько ждём ответа базы, прежде чем считать запрос зависшим. Без этого
# asyncpg ждёт вечно: оборванное TCP-соединение не отдаёт ни ответа, ни ошибки,
# и `await` внутри фоновой задачи не возвращается уже никогда. Один такой
# запрос однажды тихо остановил весь цикл клуба — ни расписания, ни ачивок,
# ни напоминаний, и ни строчки в логе. Минуты хватает с запасом: самый долгий
# наш запрос — выгрузка в Excel — считается три секунды.
COMMAND_TIMEOUT_SECONDS = 60

engine = create_async_engine(
    get_config().database_url,
    pool_pre_ping=True,
    connect_args={"command_timeout": COMMAND_TIMEOUT_SECONDS},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

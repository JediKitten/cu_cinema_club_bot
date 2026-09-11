"""Демо-данные для локального просмотра интерфейса.

Пустая база показывает пустые экраны: расписание без показов, профиль без
оценок, лента без отметок — и по такому виду нельзя судить ни о вёрстке, ни
об удобстве. Скрипт наполняет локальную базу ровно настолько, чтобы каждый
экран было на что смотреть.

Только для локальной разработки. Запускается по имени той же базы, что
в `.env`, и ничего не удаляет: повторный запуск ничего не дублирует.

Запуск:  ./venv/bin/python -m app.preview_seed
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.db import SessionLocal
from app.models import Confirmation, Favourite, Film, Hall, User
from app.models.enums import ConfirmationState, InterestKind, UserRole
from app.services import events, interests, ratings
from app.services.settings import SettingsService

logger = logging.getLogger("preview_seed")

# Четыре роли — чтобы посмотреть приложение глазами каждой. tg_id из диапазона,
# который Telegram не выдаёт живым людям, так что с настоящими не столкнутся.
PERSONAS: list[tuple[int, str, str, UserRole]] = [
    (900001, "Зритель Демо", "demo_viewer", UserRole.USER),
    (900002, "Модератор Демо", "demo_moderator", UserRole.MODERATOR),
    (900003, "Админ Демо", "demo_admin", UserRole.ADMIN),
    (900004, "Главный Демо", "demo_boss", UserRole.SUPERADMIN),
]


async def ensure_personas(session) -> dict[UserRole, User]:
    """Заводит по человеку на каждую роль и открывает им доступ."""
    people: dict[UserRole, User] = {}
    for tg_id, name, username, role in PERSONAS:
        user = (
            await session.execute(sa.select(User).where(User.tg_id == tg_id))
        ).scalar_one_or_none()
        if user is None:
            user = User(tg_id=tg_id, display_name=name, tg_username=username)
            session.add(user)
        user.display_name = name
        user.tg_username = username
        user.role = role
        # Бета-гейт не должен мешать смотреть интерфейс.
        user.access_granted_at = user.access_granted_at or datetime.now(UTC)
        user.onboarded_at = user.onboarded_at or datetime.now(UTC)
        people[role] = user
    await session.commit()
    return people


async def ensure_hall(session) -> Hall:
    hall = (await session.execute(sa.select(Hall).limit(1))).scalar_one_or_none()
    if hall is None:
        hall = Hall(name="Ауд. 402 (демо)", capacity=45)
        session.add(hall)
        await session.commit()
    return hall


async def ensure_event(session, people: dict[UserRole, User], films: list[Film]) -> int | None:
    """Показ через три дня, на который записаны все демо-персоны.

    Без него «Расписание» пустое, а именно этот экран больше всех изменился.
    """
    await ensure_hall(session)
    upcoming = await events.upcoming(session)
    if upcoming:
        event = upcoming[0]
    else:
        event = await events.create(
            session,
            starts_at=datetime.now(UTC) + timedelta(days=3),
            actor_id=people[UserRole.SUPERADMIN].id,
            film_id=films[0].id if films else None,
            title=None if films else "Демо-показ",
            note="Демо-данные: показ создан для локального просмотра.",
        )

    for user in people.values():
        exists = await session.scalar(
            sa.select(Confirmation.id).where(
                Confirmation.screening_id == event.id, Confirmation.user_id == user.id
            )
        )
        if exists is None:
            session.add(
                Confirmation(
                    screening_id=event.id,
                    user_id=user.id,
                    state=ConfirmationState.CONFIRMED,
                )
            )
    await session.commit()
    return event.id


async def ensure_marks(session, people: dict[UserRole, User], films: list[Film]) -> None:
    """Отметки, оценки и любимое — чтобы каталог, профиль и лента не были пустыми."""
    if not films:
        logger.warning("В каталоге нет фильмов: сначала запустите app.import_top")
        return

    settings = SettingsService(session)
    ttl = int(await settings.get("soon_ttl_days"))
    limit = int(await settings.get("soon_limit_per_user"))

    for user in people.values():
        # Первые два фильма — в желаемое и в ближайшее, следующие — просмотрены
        # и оценены: так видно и «Мои», и распределение оценок в профиле.
        await interests.set_mark(session, user.id, films[0].id, InterestKind.WISHLIST, ttl, limit)
        if len(films) > 1:
            await interests.set_mark(session, user.id, films[1].id, InterestKind.SOON, ttl, limit)
        for offset, stars in enumerate((5, 4.5, 4, 3.5, 3)):
            index = 2 + offset
            if index < len(films):
                await interests.set_watched(session, user.id, films[index].id, True, ttl)
                await ratings.set_rating(session, user.id, films[index].id, stars)

    # Любимое в профиле — четыре плитки, ради которых профиль и затевался.
    boss = people[UserRole.SUPERADMIN]
    already = await session.scalar(
        sa.select(sa.func.count()).select_from(Favourite).where(Favourite.user_id == boss.id)
    )
    if not already:
        for position, film in enumerate(films[:4]):
            session.add(Favourite(user_id=boss.id, film_id=film.id, position=position))
    await session.commit()


async def run() -> None:
    async with SessionLocal() as session:
        films = list((await session.execute(sa.select(Film).order_by(Film.id).limit(20))).scalars())
        people = await ensure_personas(session)
        await ensure_marks(session, people, films)
        event_id = await ensure_event(session, people, films)

    logger.info("Демо-данные готовы. Фильмов в каталоге: %d, показ №%s.", len(films), event_id)
    for tg_id, name, _, role in PERSONAS:
        logger.info("  %s — tg_id=%d, роль=%s", name, tg_id, role.value)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()

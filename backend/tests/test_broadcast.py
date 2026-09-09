"""Рассылка от лица бота (расширение по просьбе клуба)."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Confirmation, Notification
from app.models.enums import ConfirmationState, NotificationKind, ScreeningStatus
from app.services import broadcast, events, notify
from app.services.broadcast import BroadcastError
from tests.conftest import SUPERADMIN_TG_ID, login
from tests.test_weights import make_film, make_user

SOON = datetime.now(UTC) + timedelta(days=3)


async def queued(session, user_id: int | None = None) -> list[Notification]:
    stmt = sa.select(Notification).where(Notification.kind == NotificationKind.ADMIN_BROADCAST)
    if user_id is not None:
        stmt = stmt.where(Notification.user_id == user_id)
    return list((await session.execute(stmt)).scalars())


async def test_message_goes_to_everyone(session):
    boss = await make_user(session, "Админ")
    anya = await make_user(session, "Аня")
    borya = await make_user(session, "Боря")
    await session.commit()

    sent = await broadcast.send(session, boss.id, "Завтра переезжаем в 204-ю")

    assert sent.recipients == 3
    assert {n.user_id for n in await queued(session)} == {boss.id, anya.id, borya.id}


async def test_message_reaches_only_those_signed_up(session):
    """«Зал переехал» нужно сказать тем, кто придёт, а не всему клубу."""
    boss = await make_user(session, "Админ")
    coming = await make_user(session, "Придёт")
    waiting = await make_user(session, "В очереди")
    gone = await make_user(session, "Отменился")
    await make_user(session, "Мимо")
    film = await make_film(session, "Кино")
    await session.commit()

    event = await events.create(session, starts_at=SOON, actor_id=boss.id, film_id=film.id)
    session.add_all(
        [
            Confirmation(
                screening_id=event.id, user_id=coming.id, state=ConfirmationState.CONFIRMED
            ),
            Confirmation(
                screening_id=event.id, user_id=waiting.id, state=ConfirmationState.WAITLIST
            ),
            Confirmation(
                screening_id=event.id, user_id=gone.id, state=ConfirmationState.CANCELLED
            ),
        ]
    )
    await session.commit()

    sent = await broadcast.send(
        session, boss.id, "Зал переехал", audience="screening", screening_id=event.id
    )

    assert sent.recipients == 2
    assert {n.user_id for n in await queued(session)} == {coming.id, waiting.id}


async def test_audience_size_is_known_before_sending(session):
    """Рассылку не отозвать: сколько человек её получат, видно до отправки."""
    await make_user(session, "Первый")
    await make_user(session, "Второй")
    await session.commit()

    assert await broadcast.audience_size(session, "all") == 2
    assert await queued(session) == []


async def test_empty_and_overlong_messages_are_refused(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    with pytest.raises(BroadcastError, match="Пустое"):
        await broadcast.send(session, boss.id, "   ")
    with pytest.raises(BroadcastError, match="длиннее"):
        await broadcast.send(session, boss.id, "а" * (broadcast.MAX_LENGTH + 1))


async def test_unknown_screening_is_refused(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    with pytest.raises(BroadcastError, match="Показ не найден"):
        await broadcast.send(session, boss.id, "Привет", audience="screening", screening_id=999999)


async def test_text_from_a_human_cannot_break_the_message(session):
    """Сообщения уходят с parse_mode=HTML: угловая скобка в тексте без
    экранирования уронила бы отправку всей рассылке."""
    boss = await make_user(session, "Админ")
    await session.commit()
    await broadcast.send(session, boss.id, "Ждём <всех> в 19:00")

    notification = (await queued(session, boss.id))[0]
    text = notify.render(notification.kind, None, "—", notification.payload)

    assert "&lt;всех&gt;" in text
    assert "<всех>" not in text


async def test_two_sends_of_the_same_text_both_arrive(session):
    """Ключ идемпотентности — на рассылку, а не на текст: повторное объявление
    тем же словами люди должны получить дважды."""
    boss = await make_user(session, "Админ")
    await session.commit()

    await broadcast.send(session, boss.id, "Напоминаю: сегодня в 19:00")
    await broadcast.send(session, boss.id, "Напоминаю: сегодня в 19:00")

    assert len(await queued(session, boss.id)) == 2


async def test_broadcast_over_http_counts_recipients(client, session):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    await login(client, 777510, "Аня")
    headers = {"Authorization": f"Bearer {me['token']}"}

    size = (await client.get("/api/admin/broadcast/audience", headers=headers)).json()
    assert size["recipients"] == 2

    sent = await client.post(
        "/api/admin/broadcast", json={"text": "Всем привет"}, headers=headers
    )
    assert sent.status_code == 200
    assert sent.json()["recipients"] == 2


async def test_ordinary_member_cannot_broadcast(client):
    them = await login(client, 777511, "Обычный")

    refused = await client.post(
        "/api/admin/broadcast",
        json={"text": "Слушайте все"},
        headers={"Authorization": f"Bearer {them['token']}"},
    )

    assert refused.status_code == 403


async def test_screening_list_covers_both_kinds_and_counts_signups(client, session):
    """Написать нужно тем, кто придёт: откуда взялся показ — из голосования
    или из ручного анонса — рассылке безразлично."""
    boss = await make_user(session, "Админ")
    guest = await make_user(session, "Гость")
    film = await make_film(session, "Кино")
    await session.commit()

    event = await events.create(session, starts_at=SOON, actor_id=boss.id, film_id=film.id)
    session.add(
        Confirmation(screening_id=event.id, user_id=guest.id, state=ConfirmationState.CONFIRMED)
    )
    await session.commit()

    targets = await broadcast.screenings(session)

    assert [(t.id, t.title, t.signed_up) for t in targets] == [(event.id, "Кино", 1)]


async def test_cancelled_screenings_are_not_offered(session):
    boss = await make_user(session, "Админ")
    film = await make_film(session, "Отменённое")
    await session.commit()
    event = await events.create(session, starts_at=SOON, actor_id=boss.id, film_id=film.id)
    event.status = ScreeningStatus.CANCELLED
    await session.commit()

    assert await broadcast.screenings(session) == []

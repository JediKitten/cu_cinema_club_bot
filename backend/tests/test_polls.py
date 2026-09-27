"""Опрос кнопками под сообщением бота."""

from app.bot import polls
from app.bot.notices import notify_keyboard
from app.models import AuditLog
from app.models.enums import NotificationKind
from app.services import notify
from tests.test_weights import make_user


def test_broadcast_with_a_poll_gets_option_buttons():
    markup = notify_keyboard(NotificationKind.ADMIN_BROADCAST, {"text": "x", "poll": "wolf-day"})
    data = [row[0].callback_data for row in markup.inline_keyboard]
    assert data == ["poll:wolf-day:0", "poll:wolf-day:1"]
    assert notify_keyboard(NotificationKind.ADMIN_BROADCAST, {"text": "x"}) is None


def test_poll_text_lists_every_option_in_full():
    text = polls.poll_text("wolf-day")
    rendered = notify.render(NotificationKind.ADMIN_BROADCAST, None, "", {"text": text})
    assert "1. Просмотр «Волка с Уолл-стрит» в четверг" in rendered
    assert "2. Просмотр «Волка с Уолл-стрит» в пятницу" in rendered


def test_chosen_option_is_checked():
    markup = polls.poll_keyboard("wolf-day", chosen=1)
    assert markup.inline_keyboard[1][0].text.startswith("✅")
    assert not markup.inline_keyboard[0][0].text.startswith("✅")


async def test_admin_sees_results_with_names(client, session):
    """Итог в админке: сколько дошло, сколько ответили, и кто за что."""
    from datetime import UTC, datetime

    from app.models import Notification
    from app.services import polls as poll_service
    from tests.conftest import SUPERADMIN_TG_ID, login

    thu, fri, silent = [await make_user(session, n) for n in ("Четверг", "Пятница", "Молчун")]
    await session.commit()
    for user in (thu, fri, silent):
        session.add(Notification(
            user_id=user.id, kind=NotificationKind.ADMIN_BROADCAST,
            dedup_key=poll_service.dedup_key("wolf-day", user.id),
            payload={}, sent_at=datetime.now(UTC),
        ))
    session.add(poll_service.record(thu.id, "wolf-day", 0))
    session.add(poll_service.record(fri.id, "wolf-day", 0))
    await session.commit()
    session.add(poll_service.record(fri.id, "wolf-day", 1))  # передумал
    await session.commit()

    auth = await login(client, SUPERADMIN_TG_ID, "Главный")
    response = await client.get(
        "/api/admin/polls", headers={"Authorization": f"Bearer {auth['token']}"}
    )

    assert response.status_code == 200, response.text
    [poll] = response.json()
    assert (poll["delivered"], poll["answered"]) == (3, 2)
    assert [option["votes"] for option in poll["options"]] == [1, 1]
    assert [v["display_name"] for v in poll["options"][1]["voters"]] == ["Пятница"]


async def test_polls_are_for_admins_only(client, session):
    from tests.conftest import login

    auth = await login(client, 555123, "Зритель")
    response = await client.get(
        "/api/admin/polls", headers={"Authorization": f"Bearer {auth['token']}"}
    )
    assert response.status_code == 403


async def test_only_the_last_answer_counts(session):
    """Передумал — засчитывается последний ответ, а не оба."""
    first, second = await make_user(session, "Первый"), await make_user(session, "Второй")
    await session.commit()
    for user, option in ((first, 0), (first, 1), (second, 1)):
        session.add(AuditLog(actor_id=user.id, entity="poll", action="wolf-day",
                             payload={"option": option}))
        await session.commit()

    assert await polls.results(session, "wolf-day") == [0, 2]

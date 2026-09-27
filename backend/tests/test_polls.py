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


async def test_only_the_last_answer_counts(session):
    """Передумал — засчитывается последний ответ, а не оба."""
    first, second = await make_user(session, "Первый"), await make_user(session, "Второй")
    await session.commit()
    for user, option in ((first, 0), (first, 1), (second, 1)):
        session.add(AuditLog(actor_id=user.id, entity="poll", action="wolf-day",
                             payload={"option": option}))
        await session.commit()

    assert await polls.results(session, "wolf-day") == [0, 2]

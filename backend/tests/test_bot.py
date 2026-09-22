"""Знакомство с ботом при первом запуске (расширение по просьбе клуба).

Проверяем то, что можно проверить без Telegram: содержимое шагов и навигацию.
Сами обработчики — тонкая обвязка над этими функциями.
"""

from app.bot.export import analytics_keyboard, analytics_menu_text
from app.bot.notices import notify_keyboard as _notify_keyboard
from app.bot.notices import survey_keyboard
from app.bot.onboarding import TOUR, tour_keyboard, tour_text
from app.bot.votes import shortlist_keyboard, vote_keyboard
from app.services import exports

# Предел Telegram на текст сообщения.
MESSAGE_LIMIT = 4096


def test_every_step_fits_in_one_message():
    for step in range(len(TOUR)):
        text = tour_text(step)
        assert text.strip()
        assert len(text) < MESSAGE_LIMIT


def test_step_counter_is_visible():
    """Человек должен видеть, сколько ещё листать."""
    assert f"1 из {len(TOUR)}" in tour_text(0)
    assert f"{len(TOUR)} из {len(TOUR)}" in tour_text(len(TOUR) - 1)


def test_navigation_has_no_dead_ends():
    first = tour_keyboard(0, "https://example.org")
    last = tour_keyboard(len(TOUR) - 1, "https://example.org")

    def labels(keyboard):
        return [button.text for row in keyboard.inline_keyboard for button in row]

    assert not any("Назад" in text for text in labels(first))
    assert any("Дальше" in text for text in labels(first))
    assert any("Назад" in text for text in labels(last))
    assert not any("Дальше" in text for text in labels(last))


def test_app_button_is_on_every_step():
    """Знакомство можно бросить на любом шаге и сразу открыть каталог."""
    for step in range(len(TOUR)):
        keyboard = tour_keyboard(step, "https://example.org")
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        assert any(button.web_app is not None for button in buttons)


def test_without_published_url_there_is_no_broken_button():
    buttons = [button for row in tour_keyboard(0, "").inline_keyboard for button in row]
    assert all(button.web_app is None for button in buttons)


# --- Меню выгрузки (/analytics) ---------------------------------------------


def test_export_menu_fits_in_one_message():
    text = analytics_menu_text()
    assert len(text) < MESSAGE_LIMIT
    # Каждый набор должен быть подписан: кнопка «📮 Заявки» сама по себе
    # не говорит, что внутри.
    for dataset in exports.DATASETS:
        assert dataset.summary in text


def test_every_dataset_has_its_own_button():
    buttons = [button for row in analytics_keyboard().inline_keyboard for button in row]
    keys = [button.callback_data.removeprefix("dl:") for button in buttons]

    assert keys == [dataset.key for dataset in exports.DATASETS] + [exports.EVERYTHING]
    # Telegram режет callback_data на 64 байтах — ключи должны быть короткими.
    assert all(len(button.callback_data.encode()) <= 64 for button in buttons)


def test_everything_is_a_row_of_its_own():
    """«Выгрузить всё» — другой по смыслу шаг, и попасть в него мимоходом,
    целясь в соседнюю кнопку, не должно."""
    last = analytics_keyboard().inline_keyboard[-1]
    assert len(last) == 1 and last[0].callback_data == f"dl:{exports.EVERYTHING}"


# --- Кнопки голосования под уведомлением ------------------------------------

SHORTLIST_PAYLOAD = {
    "round_id": 7,
    "week_start": "2026-09-21",
    "films": [{"id": 1, "title": "Интерстеллар"}, {"id": 2, "title": "Начало"}],
    "in_english": True,
}


def flat(keyboard):
    return [button for row in keyboard.inline_keyboard for button in row]


def test_every_film_gets_its_own_button():
    buttons = flat(shortlist_keyboard(SHORTLIST_PAYLOAD))
    assert [button.callback_data for button in buttons] == ["v:7:1", "v:7:2"]
    # Telegram режет callback_data на 64 байтах.
    assert all(len(button.callback_data.encode()) <= 64 for button in buttons)


def test_nothing_chosen_means_no_app_button():
    """Звать выбирать вечера, пока не отмечен ни один фильм, рано — и лишняя
    кнопка внизу перетягивает нажатие на себя."""
    rows = shortlist_keyboard(SHORTLIST_PAYLOAD).inline_keyboard
    assert len(rows) == 2
    assert all(button.web_app is None for row in rows for button in row)


def test_first_choice_brings_the_app_button(monkeypatch):
    monkeypatch.setattr("app.bot.common.current_miniapp_url", lambda: "https://example.org")
    rows = vote_keyboard(
        7, [(1, "Интерстеллар"), (2, "Начало")], {1}, "2026-09-21"
    ).inline_keyboard

    assert rows[0][0].text.startswith("✅")
    assert rows[1][0].text.startswith("▫️")
    # Без недели в адресе приложение откроет расписание текущей, и до
    # бюллетеня останется ещё одно нажатие.
    assert rows[-1][0].web_app is not None
    assert rows[-1][0].web_app.url.endswith("?tab=vote&week=2026-09-21")


def test_old_notifications_without_ids_go_out_plain():
    """В очереди лежат записи со старым payload — кнопок к ним не собрать,
    и сообщение должно уйти обычным текстом, а не упасть."""
    assert shortlist_keyboard({"films": ["Начало"]}) is None
    assert shortlist_keyboard({}) is None


def test_long_title_is_trimmed_with_an_ellipsis():
    long = "Господин Никто и его бесконечно длинное название"
    text = vote_keyboard(7, [(1, long)], set()).inline_keyboard[0][0].text
    assert text.endswith("…") and len(text) < len(long)


def test_the_announcement_goes_out_with_its_buttons(monkeypatch):
    """Клавиатуру к уведомлению собирает бот, а не сервис рассылки, — и без
    этой ветки сообщение ушло бы голым текстом, как раньше."""
    from app.models.enums import NotificationKind

    monkeypatch.setattr("app.bot.common.current_miniapp_url", lambda: "https://example.org")
    markup = _notify_keyboard(NotificationKind.SHORTLIST_PUBLISHED, SHORTLIST_PAYLOAD)

    assert markup is not None
    assert [button.callback_data for button in flat(markup)] == ["v:7:1", "v:7:2"]


# --- Живучесть фоновых задач ------------------------------------------------


async def test_a_hung_job_does_not_stop_the_loop(monkeypatch):
    """Зависший запрос не должен уносить с собой весь цикл клуба.

    `except Exception` вокруг тела цикла зависание не ловит: исключения нет,
    `await` просто не возвращается. Однажды так и случилось — расписание,
    ачивки и напоминания не двигались восемнадцать часов, уведомления при
    этом продолжали уходить, и в логе не было ни строчки.
    """
    import asyncio

    from app.bot import loops as botmod

    monkeypatch.setattr(botmod, "JOB_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(botmod, "JOBS_INTERVAL_SECONDS", 0.01)

    started = 0

    async def hang(session):
        nonlocal started
        started += 1
        await asyncio.sleep(30)

    monkeypatch.setattr(botmod.cycle, "tick", hang)

    task = asyncio.create_task(botmod.jobs_loop())
    await asyncio.sleep(0.5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert started >= 2, "после зависания цикл обязан зайти на следующий круг"


# --- Кнопка под напоминанием об опросе --------------------------------------


def test_the_survey_reminder_leads_straight_to_the_form(monkeypatch):
    """Сообщение звало «оценить в приложении», а приложение открывалось
    на каталоге: форму надо было ещё найти."""
    from app.models.enums import NotificationKind

    monkeypatch.setattr("app.bot.common.current_miniapp_url", lambda: "https://example.org")
    markup = _notify_keyboard(NotificationKind.FEEDBACK_REMINDER, {"screening_id": 12})

    assert markup is not None
    button = flat(markup)[0]
    assert button.web_app is not None
    assert button.web_app.url.endswith("?survey=12")

    # Без адреса приложения кнопка была бы битой — лучше её не рисовать.
    monkeypatch.setattr("app.bot.common.current_miniapp_url", lambda: "")
    assert survey_keyboard(12) is None
    assert survey_keyboard(None) is None

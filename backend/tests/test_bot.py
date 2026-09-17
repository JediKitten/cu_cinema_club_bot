"""Знакомство с ботом при первом запуске (расширение по просьбе клуба).

Проверяем то, что можно проверить без Telegram: содержимое шагов и навигацию.
Сами обработчики — тонкая обвязка над этими функциями.
"""

from app.bot import (
    TOUR,
    _notify_keyboard,
    analytics_keyboard,
    analytics_menu_text,
    shortlist_keyboard,
    tour_keyboard,
    tour_text,
    vote_keyboard,
)
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
    monkeypatch.setattr("app.bot.current_miniapp_url", lambda: "https://example.org")
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

    monkeypatch.setattr("app.bot.current_miniapp_url", lambda: "https://example.org")
    markup = _notify_keyboard(NotificationKind.SHORTLIST_PUBLISHED, SHORTLIST_PAYLOAD)

    assert markup is not None
    assert [button.callback_data for button in flat(markup)] == ["v:7:1", "v:7:2"]

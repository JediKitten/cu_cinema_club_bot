"""Знакомство с ботом при первом запуске (расширение по просьбе клуба).

Проверяем то, что можно проверить без Telegram: содержимое шагов и навигацию.
Сами обработчики — тонкая обвязка над этими функциями.
"""

from app.bot import TOUR, analytics_keyboard, analytics_menu_text, tour_keyboard, tour_text
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

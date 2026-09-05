"""Сквозная проверка API: вход через initData → отметка → рейтинг → песочница.

Ходим по приложению через ASGITransport, без поднятия сервера.
"""

from datetime import date

import pytest

from app.config import get_config
from app.models import Film
from app.models.enums import UserRole
from tests.conftest import SUPERADMIN_TG_ID, login, make_init_data


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_forged_init_data_rejected(client):
    forged = make_init_data(555, "Злоумышленник", token="wrong-token")
    response = await client.post("/api/auth/telegram", json={"init_data": forged})
    assert response.status_code == 401


async def test_bootstrap_superadmin_gets_role(client):
    auth = await login(client, SUPERADMIN_TG_ID, "Главный")
    assert auth["user"]["role"] == UserRole.SUPERADMIN
    ordinary = await login(client, 777002, "Студент")
    assert ordinary["user"]["role"] == UserRole.USER


async def test_anonymous_request_rejected(client):
    assert (await client.get("/api/me/interests")).status_code == 401


async def test_interest_flow(client, session):
    """Три состояния и переходы между ними через HTTP (§4, уточнение клуба)."""
    film = Film(title_ru="Сталкер", title_orig="Stalker", year=1979)
    session.add(film)
    await session.commit()

    auth = await login(client, 777010, "Зритель")
    headers = {"Authorization": f"Bearer {auth['token']}"}

    created = await client.post(
        f"/api/films/{film.id}/interest", json={"kind": "wishlist"}, headers=headers
    )
    assert created.status_code == 201
    assert created.json()["kinds"] == ["wishlist"]

    # Вторая кнопка вытесняет первую: вместе состояния стоять не могут.
    switched = await client.post(
        f"/api/films/{film.id}/interest", json={"kind": "soon"}, headers=headers
    )
    assert switched.json()["kinds"] == ["soon"]
    assert switched.json()["expires_at"] is not None

    # Повторное нажатие той же кнопки ничего не ломает.
    again = await client.post(
        f"/api/films/{film.id}/interest", json={"kind": "soon"}, headers=headers
    )
    assert again.status_code == 201
    assert again.json()["kinds"] == ["soon"]

    card = (await client.get(f"/api/films/{film.id}", headers=headers)).json()
    assert card["interested_count"] == 1
    assert card["my_interests"] == ["soon"]
    assert card["internal_rating"] is None  # оценок нет — рейтинг скрыт (§11)

    removed = await client.delete(f"/api/films/{film.id}/interest", headers=headers)
    assert removed.json()["kinds"] == []


async def test_watched_is_independent_of_marks(client, session):
    """«Просмотрено» не мешает хотеть пересмотреть."""
    film = Film(title_ru="Солярис", year=1972)
    session.add(film)
    await session.commit()

    auth = await login(client, 777015, "Зритель")
    headers = {"Authorization": f"Bearer {auth['token']}"}

    watched = await client.post(
        f"/api/films/{film.id}/watched", json={"watched": True}, headers=headers
    )
    assert watched.json()["watched"] is True
    assert watched.json()["kinds"] == []

    marked = await client.post(
        f"/api/films/{film.id}/interest", json={"kind": "wishlist"}, headers=headers
    )
    assert marked.json()["watched"] is True
    assert marked.json()["kinds"] == ["wishlist"]

    card = (await client.get(f"/api/films/{film.id}", headers=headers)).json()
    assert card["watched"] is True
    assert card["my_interests"] == ["wishlist"]

    unwatched = await client.post(
        f"/api/films/{film.id}/watched", json={"watched": False}, headers=headers
    )
    assert unwatched.json()["watched"] is False
    assert unwatched.json()["kinds"] == ["wishlist"]  # отметка не пострадала


async def test_soon_limit_enforced(client, session):
    films = [Film(title_ru=f"Фильм {i}") for i in range(12)]
    session.add_all(films)
    await session.commit()

    auth = await login(client, 777011, "Жадный")
    headers = {"Authorization": f"Bearer {auth['token']}"}

    # Лимит по умолчанию — 10.
    for film in films[:10]:
        response = await client.post(
            f"/api/films/{film.id}/interest", json={"kind": "soon"}, headers=headers
        )
        assert response.status_code == 201

    overflow = await client.post(
        f"/api/films/{films[10].id}/interest", json={"kind": "soon"}, headers=headers
    )
    assert overflow.status_code == 409
    assert "Лимит" in overflow.json()["detail"]

    # «Желаемое» лимитом не ограничено.
    assert (
        await client.post(
            f"/api/films/{films[10].id}/interest", json={"kind": "wishlist"}, headers=headers
        )
    ).status_code == 201


async def test_settings_require_superadmin(client, session):
    ordinary = await login(client, 777012, "Обычный")
    response = await client.patch(
        "/api/admin/settings",
        json={"values": {"soon_weight": 99}},
        headers={"Authorization": f"Bearer {ordinary['token']}"},
    )
    assert response.status_code == 403


async def test_settings_validation_and_sandbox(client, session):
    film = Film(title_ru="Солярис")
    session.add(film)
    await session.commit()

    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}

    viewer = await login(client, 777013, "Голосующий")
    await client.post(
        f"/api/films/{film.id}/interest",
        json={"kind": "soon"},
        headers={"Authorization": f"Bearer {viewer['token']}"},
    )

    # Значение вне границ реестра отклоняется.
    bad = await client.patch(
        "/api/admin/settings", json={"values": {"soon_ttl_days": 0}}, headers=headers
    )
    assert bad.status_code == 422

    unknown = await client.patch(
        "/api/admin/settings", json={"values": {"нет_такого": 1}}, headers=headers
    )
    assert unknown.status_code == 422

    baseline = (await client.get("/api/admin/rankings", headers=headers)).json()
    assert baseline["by_weight"][0]["weight"] == pytest.approx(3.0)

    # Песочница считает с другими коэффициентами и ничего не сохраняет.
    sandbox = await client.post(
        "/api/admin/settings/sandbox", json={"soon_weight": 12.5}, headers=headers
    )
    assert sandbox.json()["by_weight"][0]["weight"] == pytest.approx(12.5)

    after = (await client.get("/api/admin/rankings", headers=headers)).json()
    assert after["by_weight"][0]["weight"] == pytest.approx(3.0)

    # А сохранение — меняет.
    saved = await client.patch(
        "/api/admin/settings", json={"values": {"soon_weight": 7}}, headers=headers
    )
    assert saved.status_code == 200
    changed = (await client.get("/api/admin/rankings", headers=headers)).json()
    assert changed["by_weight"][0]["weight"] == pytest.approx(7.0)


async def test_film_request_moderation(client, session):
    author = await login(client, 777014, "Автор заявки")
    author_headers = {"Authorization": f"Bearer {author['token']}"}

    created = await client.post(
        "/api/film-requests",
        json={"raw_title": "Редкое кино", "raw_year": 1998, "note": "видел на фестивале"},
        headers=author_headers,
    )
    assert created.status_code == 201
    request_id = created.json()["id"]

    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    boss_headers = {"Authorization": f"Bearer {boss['token']}"}

    pending = (await client.get("/api/admin/film-requests", headers=boss_headers)).json()
    assert [r["id"] for r in pending] == [request_id]

    rejected = await client.post(
        f"/api/admin/film-requests/{request_id}",
        json={"approve": False, "comment": "Нет прав на показ"},
        headers=boss_headers,
    )
    assert rejected.json()["status"] == "rejected"

    # Повторная обработка той же заявки — конфликт, а не молчаливая перезапись.
    assert (
        await client.post(
            f"/api/admin/film-requests/{request_id}",
            json={"approve": False},
            headers=boss_headers,
        )
    ).status_code == 409

    mine = (await client.get("/api/me/film-requests", headers=author_headers)).json()
    assert mine[0]["resolution_comment"] == "Нет прав на показ"


async def test_missing_bot_token_does_not_leak_config(client, monkeypatch):
    """Ненастроенный сервер отвечает 503 и не называет переменные окружения."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_config.cache_clear()

    response = await client.post(
        "/api/auth/telegram", json={"init_data": make_init_data(777020, "Кто-то")}
    )
    assert response.status_code == 503
    assert "TELEGRAM_BOT_TOKEN" not in response.text


async def test_directors_reach_the_client(client, session):
    """Поле есть в схеме со значением по умолчанию, поэтому забытая передача
    в ответе выглядит не как ошибка, а как фильм без режиссёра."""
    film = Film(
        title_ru="Сталкер",
        title_orig="Stalker",
        year=1979,
        directors=["Андрей Тарковский"],
    )
    session.add(film)
    await session.commit()

    auth = await login(client, 777030, "Зритель")
    headers = {"Authorization": f"Bearer {auth['token']}"}

    card = (await client.get(f"/api/films/{film.id}", headers=headers)).json()
    assert card["directors"] == ["Андрей Тарковский"]

    listing = (await client.get("/api/films", headers=headers)).json()
    assert listing[0]["directors"] == ["Андрей Тарковский"]

    marked = await client.post(
        f"/api/films/{film.id}/interest", json={"kind": "wishlist"}, headers=headers
    )
    assert marked.json()["film"]["directors"] == ["Андрей Тарковский"]


async def _promote(session, tg_id: int, role: UserRole) -> None:
    import sqlalchemy as sa

    from app.models import User

    await session.execute(sa.update(User).where(User.tg_id == tg_id).values(role=role))
    await session.commit()


async def test_round_flow_and_roles(client, session):
    films = [Film(title_ru=f"Фильм {i}") for i in range(3)]
    session.add_all(films)
    await session.commit()

    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    boss_headers = {"Authorization": f"Bearer {boss['token']}"}

    # Обычный пользователь админку не видит.
    plain = await login(client, 777040, "Студент")
    assert (
        await client.get(
            "/api/admin/round", headers={"Authorization": f"Bearer {plain['token']}"}
        )
    ).status_code == 403

    assert (await client.get("/api/admin/round", headers=boss_headers)).json() is None

    opened = await client.post("/api/admin/round", json={}, headers=boss_headers)
    assert opened.status_code == 201
    body = opened.json()
    assert body["stage"] == "collecting"
    assert len(body["slots"]) == 7
    # Понедельник следующей недели.
    assert date.fromisoformat(body["week_start"]).weekday() == 0

    # Несуществующий фильм в шорт-лист не пройдёт.
    bad = await client.put(
        "/api/admin/round/shortlist", json={"film_ids": [99999]}, headers=boss_headers
    )
    assert bad.status_code == 422

    chosen = [films[0].id, films[2].id]
    saved = await client.put(
        "/api/admin/round/shortlist", json={"film_ids": chosen}, headers=boss_headers
    )
    assert saved.status_code == 200
    assert [item["film_id"] for item in saved.json()["shortlist"]] == chosen
    assert saved.json()["stage"] == "shortlist_review"

    published = await client.post("/api/admin/round/shortlist/publish", headers=boss_headers)
    assert published.json()["stage"] == "slot_voting"

    # Повторная публикация — конфликт, а не молчаливый успех.
    assert (
        await client.post("/api/admin/round/shortlist/publish", headers=boss_headers)
    ).status_code == 409


async def test_moderator_may_build_shortlist_but_not_block_evenings(client, session):
    """§9: закрытие этапа 1 доступно модератору, блокировка вечеров — нет."""
    film = Film(title_ru="Кин-дза-дза!")
    session.add(film)
    await session.commit()

    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    opened = await client.post(
        "/api/admin/round", json={}, headers={"Authorization": f"Bearer {boss['token']}"}
    )
    slot_id = opened.json()["slots"][0]["id"]

    moderator = await login(client, 777041, "Модератор")
    await _promote(session, 777041, UserRole.MODERATOR)
    headers = {"Authorization": f"Bearer {moderator['token']}"}

    allowed = await client.put(
        "/api/admin/round/shortlist", json={"film_ids": [film.id]}, headers=headers
    )
    assert allowed.status_code == 200

    refused = await client.post(
        f"/api/admin/round/slots/{slot_id}/block",
        json={"blocked": True, "reason": "пары"},
        headers=headers,
    )
    assert refused.status_code == 403


async def test_blocked_evening_is_reported(client, session):
    film = Film(title_ru="Солярис")
    session.add(film)
    await session.commit()

    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}
    opened = await client.post("/api/admin/round", json={}, headers=headers)
    slot_id = opened.json()["slots"][2]["id"]

    blocked = await client.post(
        f"/api/admin/round/slots/{slot_id}/block",
        json={"blocked": True, "reason": "праздник"},
        headers=headers,
    )
    slot = next(s for s in blocked.json()["slots"] if s["id"] == slot_id)
    assert slot["blocked"] is True
    assert slot["blocked_reason"] == "праздник"

    unblocked = await client.post(
        f"/api/admin/round/slots/{slot_id}/block", json={"blocked": False}, headers=headers
    )
    slot = next(s for s in unblocked.json()["slots"] if s["id"] == slot_id)
    assert slot["blocked"] is False
    assert slot["blocked_reason"] is None

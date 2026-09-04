"""Сквозная проверка API: вход через initData → отметка → рейтинг → песочница.

Ходим по приложению через ASGITransport, без поднятия сервера.
"""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_config
from app.models import Film
from app.models.enums import UserRole

BOT_TOKEN = "123456:TEST-TOKEN-FOR-SIGNATURE-CHECKS"
SUPERADMIN_TG_ID = 777001


def make_init_data(tg_id: int, first_name: str, token: str = BOT_TOKEN) -> str:
    """Подписываем initData ровно так же, как это делает Telegram."""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF_test",
        "user": json.dumps(
            {"id": tg_id, "first_name": first_name, "username": f"u{tg_id}"},
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
async def client(session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("BOOTSTRAP_SUPERADMIN_TG_ID", str(SUPERADMIN_TG_ID))
    get_config.cache_clear()

    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    get_config.cache_clear()


async def login(client, tg_id: int, name: str) -> dict:
    response = await client.post(
        "/api/auth/telegram", json={"init_data": make_init_data(tg_id, name)}
    )
    assert response.status_code == 200, response.text
    return response.json()


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

    # Обе кнопки независимы — ставим вторую, ожидаем обе.
    both = await client.post(
        f"/api/films/{film.id}/interest", json={"kind": "soon"}, headers=headers
    )
    assert sorted(both.json()["kinds"]) == ["soon", "wishlist"]
    assert both.json()["expires_at"] is not None

    # Повторное нажатие не должно быть ошибкой.
    again = await client.post(
        f"/api/films/{film.id}/interest", json={"kind": "soon"}, headers=headers
    )
    assert again.status_code == 201

    card = (await client.get(f"/api/films/{film.id}", headers=headers)).json()
    assert card["interested_count"] == 1
    assert card["internal_rating"] is None  # оценок нет — рейтинг скрыт (§11)

    removed = await client.delete(f"/api/films/{film.id}/interest?kind=soon", headers=headers)
    assert removed.json()["kinds"] == ["wishlist"]


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

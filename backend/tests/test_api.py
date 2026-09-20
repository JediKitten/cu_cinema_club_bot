"""Сквозная проверка API: вход через initData → отметка → рейтинг → песочница.

Ходим по приложению через ASGITransport, без поднятия сервера.
"""

from datetime import date

import pytest

from app.config import get_config
from app.models import Film
from app.models.enums import UserRole
from tests.conftest import (
    SUPERADMIN_TG_ID,
    login,
    make_init_data,
    open_shortlist_window,
)


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

    await open_shortlist_window(session)

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
    await open_shortlist_window(session)

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


async def test_search_does_not_duplicate_films_across_sources(client, session, monkeypatch):
    """Каталог наполнен из Кинопоиска — у фильмов пуст tmdb_id, и тот же фильм
    из TMDB показывался вторым."""
    session.add(
        Film(title_ru="Бойцовский клуб", title_orig="Fight Club", year=1999, tmdb_id=None)
    )
    await session.commit()

    async def fake_search(self, query, page=1):
        return [
            {
                "id": 550,
                "title": "Бойцовский клуб",
                "original_title": "Fight Club",
                "release_date": "1999-10-15",
                "poster_path": "/x.jpg",
            },
            {
                "id": 999,
                "title": "Другой фильм",
                "original_title": "Something Else",
                "release_date": "2001-01-01",
                "poster_path": None,
            },
        ]

    from app.services.tmdb import TmdbClient

    monkeypatch.setattr(TmdbClient, "search", fake_search)
    monkeypatch.setattr(TmdbClient, "configured", property(lambda self: True))

    auth = await login(client, 777040, "Ищущий")
    found = (
        await client.get(
            "/api/films/search?q=клуб", headers={"Authorization": f"Bearer {auth['token']}"}
        )
    ).json()

    titles = [f["title_ru"] for f in found]
    assert titles.count("Бойцовский клуб") == 1
    # Фильм из каталога, а не из TMDB: у него есть id и его можно открыть.
    assert found[0]["id"] is not None
    assert "Другой фильм" in titles


async def test_watched_works_for_film_not_yet_in_catalog(client, session, monkeypatch):
    """Кнопка «Просмотрено» должна работать и на результате поиска TMDB."""

    async def fake_movie(self, tmdb_id):
        return {
            "id": tmdb_id,
            "title": "Новинка",
            "original_title": "Newcomer",
            "release_date": "2025-05-01",
            "genres": [],
            "credits": {"crew": []},
            "videos": {"results": []},
        }

    from app.services.tmdb import TmdbClient

    monkeypatch.setattr(TmdbClient, "movie", fake_movie)
    monkeypatch.setattr(TmdbClient, "configured", property(lambda self: True))

    auth = await login(client, 777041, "Зритель")
    headers = {"Authorization": f"Bearer {auth['token']}"}

    marked = await client.post(
        "/api/watched", json={"watched": True, "tmdb_id": 12345}, headers=headers
    )
    assert marked.status_code == 200
    body = marked.json()
    assert body["watched"] is True
    # Фильм завёлся в каталоге в этот же момент.
    assert body["film"]["id"] is not None
    assert body["film"]["title_ru"] == "Новинка"


async def test_tmdb_card_opens_without_touching_the_catalog(client, session, monkeypatch):
    """Карточку фильма из поиска можно открыть, но в базу он при этом не попадает:
    иначе каталог заполнялся бы всем, что кто-то просто посмотрел."""
    import sqlalchemy as sa

    async def fake_movie(self, tmdb_id):
        return {
            "id": tmdb_id,
            "title": "Гладиатор",
            "original_title": "Gladiator",
            "release_date": "2000-05-01",
            "runtime": 155,
            "overview": "Про арену",
            "poster_path": "/g.jpg",
            "genres": [{"name": "драма"}],
            "credits": {"crew": [{"job": "Director", "name": "Ридли Скотт"}]},
            "videos": {"results": []},
            "vote_average": 8.2,
            "vote_count": 17000,
        }

    from app.services.tmdb import TmdbClient

    monkeypatch.setattr(TmdbClient, "movie", fake_movie)
    monkeypatch.setattr(TmdbClient, "configured", property(lambda self: True))

    auth = await login(client, 777050, "Любопытный")
    card = (
        await client.get(
            "/api/films/tmdb/98", headers={"Authorization": f"Bearer {auth['token']}"}
        )
    ).json()

    assert card["title_ru"] == "Гладиатор"
    assert card["directors"] == ["Ридли Скотт"]
    assert card["runtime_min"] == 155
    assert card["id"] is None
    assert card["in_catalog"] is False
    # Внутренних данных нет: отмечать фильм никто не мог.
    assert card["interested_count"] == 0
    assert card["internal_rating"] is None

    assert await session.scalar(sa.select(sa.func.count()).select_from(Film)) == 0


async def test_tmdb_card_falls_back_to_the_catalog_one(client, session, monkeypatch):
    """Если фильм уже завели, показываем полноценную карточку с данными клуба."""
    film = Film(title_ru="Гладиатор", title_orig="Gladiator", year=2000, tmdb_id=98)
    session.add(film)
    await session.commit()

    auth = await login(client, 777051, "Зритель")
    headers = {"Authorization": f"Bearer {auth['token']}"}
    await client.post(f"/api/films/{film.id}/interest", json={"kind": "soon"}, headers=headers)

    card = (await client.get("/api/films/tmdb/98", headers=headers)).json()

    assert card["id"] == film.id
    assert card["in_catalog"] is True
    assert card["interested_count"] == 1
    assert card["my_interests"] == ["soon"]


async def test_watched_list_and_wanted_sorting(client, session):
    """«Мои» показывают просмотренное, каталог умеет сортировать по числу желающих."""
    popular = Film(title_ru="Многие хотят", year=2000, kp_rating=6.0, kp_votes=10_000)
    lonely = Film(title_ru="Один хочет", year=2001, kp_rating=8.5, kp_votes=10_000)
    session.add_all([popular, lonely])
    await session.commit()

    first = await login(client, 777060, "Первый")
    second = await login(client, 777061, "Второй")
    h1 = {"Authorization": f"Bearer {first['token']}"}
    h2 = {"Authorization": f"Bearer {second['token']}"}

    for headers in (h1, h2):
        await client.post(
            f"/api/films/{popular.id}/interest", json={"kind": "soon"}, headers=headers
        )
    await client.post(f"/api/films/{lonely.id}/interest", json={"kind": "soon"}, headers=h1)

    # По весу клуба первым идёт фильм с двумя отметками, хотя внешних голосов
    # у него меньше.
    by_wanted = (await client.get("/api/films?sort=wanted", headers=h1)).json()
    assert [f["title_ru"] for f in by_wanted][:2] == ["Многие хотят", "Один хочет"]

    # По оценке Кинопоиска — наоборот.
    by_kp = (await client.get("/api/films?sort=kp", headers=h1)).json()
    assert by_kp[0]["title_ru"] == "Один хочет"

    # Просмотренное — отдельный список, отметку не отменяет.
    await client.post(f"/api/films/{popular.id}/watched", json={"watched": True}, headers=h1)
    watched = (await client.get("/api/me/watched", headers=h1)).json()
    assert [f["title_ru"] for f in watched] == ["Многие хотят"]
    assert watched[0]["my_interests"] == ["soon"]

    # У второго пользователя свой список.
    assert (await client.get("/api/me/watched", headers=h2)).json() == []


async def test_wanted_sorting_uses_weight_not_headcount(client, session):
    """Свежее «Ближайшее» весит больше давнего «Желаемого» — сортировка это учитывает."""
    from datetime import UTC, datetime, timedelta

    import sqlalchemy as sa

    from app.models import Interest

    fresh = Film(title_ru="Хотят сейчас", year=2020, ext_votes=1)
    stale = Film(title_ru="Хотели давно", year=2019, ext_votes=1)
    session.add_all([fresh, stale])
    await session.commit()

    one = await login(client, 777070, "Первый")
    h1 = {"Authorization": f"Bearer {one['token']}"}
    await client.post(f"/api/films/{fresh.id}/interest", json={"kind": "soon"}, headers=h1)

    # На старый фильм — двое, но их отметки давно затухли.
    for tg_id in (777071, 777072):
        auth = await login(client, tg_id, f"Зритель {tg_id}")
        await client.post(
            f"/api/films/{stale.id}/interest",
            json={"kind": "wishlist"},
            headers={"Authorization": f"Bearer {auth['token']}"},
        )
    await session.execute(
        sa.update(Interest)
        .where(Interest.film_id == stale.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=3000))
    )
    await session.commit()

    listed = (await client.get("/api/films?sort=wanted", headers=h1)).json()
    # Один свежий голос перевешивает двух давних: 3.0 против 2 × 0.2.
    assert [f["title_ru"] for f in listed][:2] == ["Хотят сейчас", "Хотели давно"]


async def test_catalog_sorts_by_each_source(client, session):
    """Три порядка, три источника: топ Кинопоиска, оценки TMDB, оценки клуба."""
    top = Film(title_ru="В топе", kp_top250=3, kp_rating=8.0, kp_votes=10_000, tmdb_rating=7.0,
               tmdb_votes=5_000)
    loved_abroad = Film(title_ru="Любят за рубежом", kp_rating=8.9, kp_votes=10_000,
                        tmdb_rating=8.8, tmdb_votes=5_000)
    ours = Film(title_ru="Наш выбор", kp_rating=6.6, kp_votes=10_000, tmdb_rating=6.0,
                tmdb_votes=5_000)
    session.add_all([top, loved_abroad, ours])
    await session.commit()

    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    headers = {"Authorization": f"Bearer {me['token']}"}
    await client.put(f"/api/films/{ours.id}/rating", json={"stars": 5}, headers=headers)

    # Место в топ-250 бьёт любую среднюю оценку — список курируемый.
    by_kp = (await client.get("/api/films?sort=kp", headers=headers)).json()
    assert [f["title_ru"] for f in by_kp] == ["В топе", "Любят за рубежом", "Наш выбор"]

    by_tmdb = (await client.get("/api/films?sort=tmdb", headers=headers)).json()
    assert [f["title_ru"] for f in by_tmdb] == ["Любят за рубежом", "В топе", "Наш выбор"]

    by_club = (await client.get("/api/films?sort=club", headers=headers)).json()
    assert by_club[0]["title_ru"] == "Наш выбор"


async def test_ratings_from_a_handful_of_votes_do_not_lead(client, session):
    """9,4 по десятку голосов — не оценка, а случайность: такие уходят вниз."""
    loud = Film(title_ru="Десять восторгов", tmdb_rating=9.4, tmdb_votes=10)
    solid = Film(title_ru="Проверенное", tmdb_rating=7.5, tmdb_votes=50_000)
    session.add_all([loud, solid])
    await session.commit()

    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    listing = (
        await client.get(
            "/api/films?sort=tmdb", headers={"Authorization": f"Bearer {me['token']}"}
        )
    ).json()

    assert [f["title_ru"] for f in listing] == ["Проверенное", "Десять восторгов"]


async def test_search_finds_films_by_director(client, session):
    """«Нолан» — такой же способ вспомнить фильм, как половина названия."""
    from app.models import Film
    from app.models.enums import FilmStatus

    session.add(
        Film(
            title_ru="Начало",
            title_orig="Inception",
            year=2010,
            status=FilmStatus.ACTIVE,
            directors=["Кристофер Нолан"],
        )
    )
    session.add(
        Film(
            title_ru="Крёстный отец",
            title_orig="The Godfather",
            year=1972,
            status=FilmStatus.ACTIVE,
            directors=["Фрэнсис Форд Коппола"],
        )
    )
    await session.commit()

    auth = await login(client, 777050, "Зритель")
    headers = {"Authorization": f"Bearer {auth['token']}"}

    found = (await client.get("/api/films/search?q=нолан", headers=headers)).json()
    titles = [film["title_ru"] for film in found]

    assert "Начало" in titles
    assert "Крёстный отец" not in titles

    # По названию ищется как и раньше.
    by_title = (await client.get("/api/films/search?q=крёстный", headers=headers)).json()
    assert "Крёстный отец" in [film["title_ru"] for film in by_title]


async def test_login_still_reports_access_for_cached_clients(client):
    """Вход по кодам убран, но приложение, залёгшее в кэше Telegram, решает
    по этому полю, показывать ли экран «введите код». Перестав его присылать,
    мы заперли снаружи всех, к кому новая сборка ещё не доехала."""
    auth = await login(client, 777060, "Из кэша")
    assert auth["user"]["access"] is True

    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {auth['token']}"}
    )
    assert me.json()["access"] is True


async def test_index_is_revalidated_and_assets_are_not(client):
    """index.html имя не меняет — залежавшись в кэше WebView, он держит
    человека на позавчерашней сборке. У собранных файлов имя с хешем,
    и кэшировать их можно навсегда."""
    from pathlib import Path

    from app.config import get_config
    from app.main import IMMUTABLE

    built = Path(get_config().frontend_dir)
    if not (built / "index.html").is_file():
        pytest.skip("фронтенд не собран — отдавать нечего")

    page = await client.get("/")
    assert page.headers["cache-control"] == "no-cache"

    asset = next((built / "assets").glob("*.js"), None)
    assert asset is not None
    served = await client.get(f"/assets/{asset.name}")
    assert served.headers["cache-control"] == IMMUTABLE

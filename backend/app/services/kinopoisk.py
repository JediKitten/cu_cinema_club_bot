"""Клиент kinopoisk.dev (§11).

Официального API у Кинопоиска нет; kinopoisk.dev — неофициальная обёртка со
связкой по `externalId.tmdb`. Используем его для двух вещей:
  * подобрать список фильмов (топ-250) — какие именно фильмы завозить в каталог;
  * лениво подтягивать русский рейтинг для карточек, которые кто-то открыл.

Полный каталог отсюда не тянем: бесплатный лимит запросов небольшой.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_config

BASE_URL = "https://api.kinopoisk.dev/v1.4"


class KinopoiskError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TopEntry:
    rank: int
    kp_id: int
    tmdb_id: int | None
    name: str
    year: int | None
    # Оригинальное название. У части позиций Кинопоиск не знает tmdb id —
    # тогда фильм ищется в TMDB по этому полю, оно совпадает надёжнее русского.
    alternative_name: str | None = None


class KinopoiskClient:
    def __init__(self) -> None:
        self._token = get_config().kinopoisk_api_token
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(4)

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def _request(self, path: str, params: dict[str, Any]) -> dict:
        if not self.configured:
            raise KinopoiskError("KINOPOISK_API_TOKEN не задан")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers={"X-API-KEY": self._token},
                timeout=httpx.Timeout(30.0),
                # API отвечает 301 на api.poiskkino.dev — без этого запрос
                # молча возвращает пустой редирект вместо данных.
                follow_redirects=True,
            )
        try:
            async with self._semaphore:
                response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise KinopoiskError(f"Кинопоиск недоступен: {exc.__class__.__name__}") from exc

        if response.status_code == 403:
            raise KinopoiskError("Кинопоиск: лимит запросов исчерпан или токен недействителен")
        if response.status_code >= 400:
            raise KinopoiskError(f"Кинопоиск {response.status_code}: {response.text[:200]}")
        return response.json()

    async def top250(self, limit: int) -> list[TopEntry]:
        """Первые `limit` позиций рейтинга топ-250, по возрастанию места."""
        entries: list[TopEntry] = []
        page, per_page = 1, min(limit, 250)

        while len(entries) < limit:
            data = await self._request(
                "/movie",
                {
                    "lists": "top250",
                    "sortField": "top250",
                    "sortType": "1",
                    "limit": per_page,
                    "page": page,
                    "selectFields": [
                        "id",
                        "name",
                        "alternativeName",
                        "year",
                        "top250",
                        "externalId",
                    ],
                },
            )
            docs = data.get("docs", [])
            if not docs:
                break
            for doc in docs:
                external = doc.get("externalId") or {}
                tmdb_raw = external.get("tmdb")
                entries.append(
                    TopEntry(
                        rank=doc.get("top250") or len(entries) + 1,
                        kp_id=doc["id"],
                        tmdb_id=int(tmdb_raw) if tmdb_raw else None,
                        name=doc.get("name") or "",
                        year=doc.get("year"),
                        alternative_name=doc.get("alternativeName"),
                    )
                )
            if page >= data.get("pages", page):
                break
            page += 1

        entries.sort(key=lambda e: e.rank)
        return entries[:limit]

    async def top250_full(self, limit: int) -> list[dict]:
        """Топ-250 с полями, достаточными для карточки, — когда каталог строится
        прямо из Кинопоиска, без похода в TMDB."""
        docs: list[dict] = []
        page, per_page = 1, min(limit, 250)

        while len(docs) < limit:
            data = await self._request(
                "/movie",
                {
                    "lists": "top250",
                    "sortField": "top250",
                    "sortType": "1",
                    "limit": per_page,
                    "page": page,
                    "selectFields": FULL_FIELDS,
                },
            )
            batch = data.get("docs", [])
            if not batch:
                break
            docs.extend(batch)
            if page >= data.get("pages", page):
                break
            page += 1

        docs.sort(key=lambda d: d.get("top250") or 10**6)
        return docs[:limit]

    async def popular(
        self, limit: int, min_rating: float = 6.5, min_votes: int = 5_000
    ) -> list[dict]:
        """Широкий список известного кино — топ-250 для ленты слишком короток.

        Сортировка по числу голосов, а не по рейтингу: у ленты задача не выдать
        лучшее, а показать то, о чём человек способен что-то решить за секунду.
        Порог по рейтингу лишь отсекает откровенный мусор; выбирает дальше
        рекомендация, а не этот список.

        Отбор идёт на нашей стороне намеренно. Те же условия параметрами запроса
        (`rating.kp`, `notNullFields`) заставляют Кинопоиск перебирать миллион
        документов: страница отвечает не за секунду, а за полминуты, и импорт
        упирается в таймаут. Отсортированная по голосам выдача приходит быстро,
        а отбросить неподходящее дешевле здесь.
        """
        kept: list[dict] = []
        page, per_page = 1, 250

        while len(kept) < limit:
            data = await self._request(
                "/movie",
                {
                    "type": "movie",
                    "sortField": "votes.kp",
                    "sortType": "-1",
                    "limit": per_page,
                    "page": page,
                    "selectFields": FULL_FIELDS,
                },
            )
            batch = data.get("docs", [])
            if not batch:
                break
            for doc in batch:
                if _worth_showing(doc, min_rating, min_votes):
                    kept.append(doc)
            if page >= data.get("pages", page):
                break
            page += 1

        return kept[:limit]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _worth_showing(doc: dict, min_rating: float, min_votes: int) -> bool:
    """Годится ли фильм для ленты: карточку решают за секунду.

    Без постера и описания решать не по чему, а низкий рейтинг при большом
    числе голосов — это уже приговор, а не неизвестность.
    """
    if not (doc.get("poster") or {}).get("url"):
        return False
    if not (doc.get("description") or doc.get("shortDescription")):
        return False
    rating = (doc.get("rating") or {}).get("kp")
    votes = (doc.get("votes") or {}).get("kp")
    return bool(rating and votes) and rating >= min_rating and votes >= min_votes


_client: KinopoiskClient | None = None


def get_kinopoisk() -> KinopoiskClient:
    global _client
    if _client is None:
        _client = KinopoiskClient()
    return _client


# --- Запись в каталог -------------------------------------------------------

FULL_FIELDS = [
    "id",
    "name",
    "alternativeName",
    "year",
    "movieLength",
    "description",
    "shortDescription",
    "genres",
    "poster",
    "rating",
    "votes",
    "videos",
    "top250",
    "persons",
    # Связка с TMDB: по ней рейтинг TMDB подтягивается точно, а не поиском
    # по названию, и по ней же узнаётся фильм, уже заведённый из TMDB.
    "externalId",
]


def film_fields(doc: dict) -> dict:
    """Документ Кинопоиска → колонки films.

    В poster_path кладём абсолютный URL: у Кинопоиска постеры лежат на своём CDN,
    и собрать их из пути, как у TMDB, нельзя. poster_url() различает по схеме.
    """
    trailers = ((doc.get("videos") or {}).get("trailers")) or []
    trailer_key = None
    for video in trailers:
        url = video.get("url") or ""
        if "youtube.com" in url or "youtu.be" in url:
            trailer_key = url.rsplit("/", 1)[-1].split("?v=")[-1].split("&")[0]
            break

    rating = doc.get("rating") or {}
    votes = doc.get("votes") or {}

    # В persons приходит вся съёмочная группа — от актёров до художников;
    # режиссёров отбираем по enProfession, он не зависит от языка ответа.
    directors = [
        person.get("name") or person.get("enName")
        for person in (doc.get("persons") or [])
        if person.get("enProfession") == "director" and (person.get("name") or person.get("enName"))
    ]

    return {
        "kp_id": doc["id"],
        "title_ru": doc.get("name") or doc.get("alternativeName") or "Без названия",
        "title_orig": doc.get("alternativeName"),
        "year": doc.get("year"),
        "runtime_min": doc.get("movieLength"),
        "overview": doc.get("description") or doc.get("shortDescription") or None,
        "poster_path": (doc.get("poster") or {}).get("url"),
        "trailer_key": trailer_key,
        "genres": [g["name"] for g in doc.get("genres", []) if g.get("name")],
        "directors": directors,
        "ext_rating": rating.get("kp"),
        "ext_votes": votes.get("kp"),
        "kp_rating": rating.get("kp"),
        "kp_votes": votes.get("kp"),
        "kp_top250": doc.get("top250"),
    }


def tmdb_id_of(doc: dict) -> int | None:
    """Идентификатор фильма в TMDB, если Кинопоиск его знает."""
    raw = (doc.get("externalId") or {}).get("tmdb")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


async def upsert_from_kinopoisk(session, doc: dict):
    """Идемпотентная запись — зеркало upsert_from_tmdb.

    Фильм узнаётся сначала по kp_id, а если такого ещё нет — по tmdb_id: тот же
    фильм мог приехать раньше из TMDB, и вторая строка для него превратила бы
    каталог в список с двойниками. Такую строку дополняем данными Кинопоиска,
    а не заводим соседнюю.
    """
    import sqlalchemy as sa

    from app.models import Film

    fields = film_fields(doc)
    tmdb_id = tmdb_id_of(doc)

    film = (
        await session.execute(sa.select(Film).where(Film.kp_id == fields["kp_id"]))
    ).scalar_one_or_none()
    if film is None and tmdb_id is not None:
        film = (
            await session.execute(sa.select(Film).where(Film.tmdb_id == tmdb_id))
        ).scalar_one_or_none()

    if film is None:
        film = Film(**fields, tmdb_id=tmdb_id)
        session.add(film)
    else:
        for key, value in fields.items():
            setattr(film, key, value)
        # Связку с TMDB проставляем только в пустое место: чужой id перезаписью
        # мы бы «переселили» фильм на другую карточку.
        if film.tmdb_id is None:
            film.tmdb_id = tmdb_id

    await session.commit()
    await session.refresh(film)
    return film

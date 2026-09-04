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

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_client: KinopoiskClient | None = None


def get_kinopoisk() -> KinopoiskClient:
    global _client
    if _client is None:
        _client = KinopoiskClient()
    return _client

"""Клиент TMDB (§11).

На старте выбрана ленивая схема: каталог наполняется по мере того, как люди ищут
и отмечают фильмы. Массовый импорт из ежедневного дампа ID добавляется поверх этого
же `upsert_from_tmdb` — отдельного пути записи не появится.

Постеры не храним: сохраняем poster_path, URL собирается на лету с CDN.
"""

import asyncio
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_config
from app.models import Film

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"


class TmdbError(RuntimeError):
    pass


def poster_url(poster_path: str | None, size: str = "w342") -> str | None:
    return f"{IMAGE_BASE}/{size}{poster_path}" if poster_path else None


class TmdbClient:
    """Один экземпляр на процесс: httpx.AsyncClient держит пул соединений,
    пересоздавать его на каждый запрос дорого."""

    def __init__(self) -> None:
        config = get_config()
        self._language = config.tmdb_language
        self._token = config.tmdb_api_token
        self._client: httpx.AsyncClient | None = None
        # TMDB держит ~20 rps; ограничиваем себя сами, чтобы не ловить 429.
        self._semaphore = asyncio.Semaphore(16)

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def _request(self, path: str, **params: Any) -> dict:
        if not self.configured:
            raise TmdbError("TMDB_API_TOKEN не задан")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(10.0),
            )
        async with self._semaphore:
            response = await self._client.get(path, params={"language": self._language, **params})
        if response.status_code >= 400:
            raise TmdbError(f"TMDB {response.status_code}: {response.text[:200]}")
        return response.json()

    async def search(self, query: str, page: int = 1) -> list[dict]:
        data = await self._request("/search/movie", query=query, page=page, include_adult="false")
        return data.get("results", [])

    async def movie(self, tmdb_id: int) -> dict:
        return await self._request(f"/movie/{tmdb_id}", append_to_response="videos")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_client: TmdbClient | None = None


def get_tmdb() -> TmdbClient:
    global _client
    if _client is None:
        _client = TmdbClient()
    return _client


def _trailer_key(payload: dict) -> str | None:
    videos = (payload.get("videos") or {}).get("results", [])
    # Официальный трейлер на YouTube предпочтительнее тизера или клипа.
    for wanted in ("Trailer", "Teaser"):
        for video in videos:
            if video.get("site") == "YouTube" and video.get("type") == wanted:
                return video.get("key")
    return None


def _film_fields(payload: dict) -> dict:
    release_date = payload.get("release_date") or ""
    return {
        "tmdb_id": payload["id"],
        "title_ru": payload.get("title") or payload.get("original_title") or "Без названия",
        "title_orig": payload.get("original_title"),
        "year": int(release_date[:4]) if release_date[:4].isdigit() else None,
        "runtime_min": payload.get("runtime"),
        "overview": payload.get("overview") or None,
        "poster_path": payload.get("poster_path"),
        "backdrop_path": payload.get("backdrop_path"),
        "trailer_key": _trailer_key(payload),
        "genres": [g["name"] for g in payload.get("genres", []) if g.get("name")],
        "ext_rating": payload.get("vote_average"),
        "ext_votes": payload.get("vote_count"),
    }


async def upsert_from_tmdb(session: AsyncSession, payload: dict) -> Film:
    """Единственная точка записи фильма из TMDB — и для ленивой подгрузки,
    и для будущего массового импорта. Идемпотентна по tmdb_id."""
    fields = _film_fields(payload)
    stmt = insert(Film).values(**fields, tmdb_synced_at=sa.func.now())
    stmt = stmt.on_conflict_do_update(
        index_elements=[Film.tmdb_id],
        set_={**fields, "tmdb_synced_at": sa.func.now()},
    ).returning(Film)
    film = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return film


async def ensure_film(session: AsyncSession, tmdb_id: int) -> Film:
    """Возвращает фильм из базы, подтягивая его из TMDB при первом обращении."""
    existing = (
        await session.execute(sa.select(Film).where(Film.tmdb_id == tmdb_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return await upsert_from_tmdb(session, await get_tmdb().movie(tmdb_id))

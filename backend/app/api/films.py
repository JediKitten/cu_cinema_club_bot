from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models import Feedback, Film, Interest, User
from app.models.enums import FilmStatus
from app.schemas import FilmBrief, FilmCard, ReviewOut
from app.services import interests as marks_service
from app.services import matching
from app.services.interests import MarkState
from app.services.settings import SettingsService
from app.services.tmdb import TmdbError, film_fields, get_tmdb, poster_url

router = APIRouter(prefix="/api/films", tags=["films"])

SortKey = Literal["recent", "alphabetical", "year", "popular"]


def _brief(film: Film, marks: dict[int, MarkState] | None = None) -> FilmBrief:
    mark = (marks or {}).get(film.id) or MarkState(None, None, None, False, False)
    return FilmBrief(
        id=film.id,
        tmdb_id=film.tmdb_id,
        title_ru=film.title_ru,
        title_orig=film.title_orig,
        year=film.year,
        poster_url=poster_url(film.poster_path),
        genres=list(film.genres or []),
        directors=list(film.directors or []),
        in_catalog=True,
        my_interests=[mark.effective_kind] if mark.effective_kind else [],
        can_renew_soon=mark.can_renew_soon,
        soon_expires_at=mark.expires_at,
        watched=mark.watched,
    )


async def _my_marks(
    session: AsyncSession, user_id: int, films: list[Film]
) -> dict[int, MarkState]:
    """Одним запросом на весь список — иначе каталог давал бы запрос на карточку."""
    ttl = int(await SettingsService(session).get("soon_ttl_days"))
    return await marks_service.marks_for_films(session, user_id, [f.id for f in films], ttl)


@router.get("/search", response_model=list[FilmBrief])
async def search_films(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=2, max_length=200)],
) -> list[FilmBrief]:
    """Сначала локальная база, затем добор из TMDB.

    Фильм из TMDB возвращается с id=None: в каталог он попадёт при первой отметке,
    иначе поиск засорял бы базу всем, что кто-то когда-то набрал.
    """
    pattern = f"%{q}%"
    local = (
        (
            await session.execute(
                sa.select(Film)
                .where(
                    Film.status == FilmStatus.ACTIVE,
                    sa.or_(Film.title_ru.ilike(pattern), Film.title_orig.ilike(pattern)),
                )
                .order_by(sa.func.coalesce(Film.ext_votes, 0).desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    marks = await _my_marks(session, user.id, list(local))
    results = [_brief(film, marks) for film in local]
    seen_tmdb = {film.tmdb_id for film in local if film.tmdb_id}
    # Каталог наполнен из Кинопоиска, у этих фильмов tmdb_id пуст. Отсеивать
    # дубли только по нему нельзя: тот же фильм из TMDB показался бы вторым.
    seen_titles: set[tuple[str, int]] = set()
    for film in local:
        seen_titles |= matching.keys(film.title_ru, film.title_orig, film.year)

    tmdb = get_tmdb()
    if tmdb.configured and len(results) < 20:
        try:
            for item in await tmdb.search(q):
                if item["id"] in seen_tmdb:
                    continue
                release = item.get("release_date") or ""
                year = int(release[:4]) if release[:4].isdigit() else None
                if matching.keys(item.get("title"), item.get("original_title"), year) & seen_titles:
                    continue
                results.append(
                    FilmBrief(
                        id=None,
                        tmdb_id=item["id"],
                        title_ru=item.get("title") or item.get("original_title") or "Без названия",
                        title_orig=item.get("original_title"),
                        year=year,
                        poster_url=poster_url(item.get("poster_path")),
                        in_catalog=False,
                    )
                )
        except TmdbError:
            # Каталог не должен падать целиком из-за недоступности TMDB —
            # локальных результатов достаточно, чтобы продолжить работу.
            pass
    return results[:40]


@router.get("", response_model=list[FilmBrief])
async def browse_films(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    sort: SortKey = "popular",
    genre: str | None = None,
    offset: int = 0,
    limit: Annotated[int, Query(ge=1, le=60)] = 30,
) -> list[FilmBrief]:
    """Сортировка по умолчанию — по популярности.

    §11 просит обратного: эффект присоединения к большинству убивает хвост
    каталога. Изменено по решению клуба, см. «Отступления от спека» в README.
    """
    stmt = sa.select(Film).where(Film.status == FilmStatus.ACTIVE)
    if genre:
        stmt = stmt.where(Film.genres.any(genre))

    order = {
        "recent": Film.created_at.desc(),
        "alphabetical": Film.title_ru.asc(),
        "year": sa.func.coalesce(Film.year, 0).desc(),
        "popular": sa.func.coalesce(Film.ext_votes, 0).desc(),
    }[sort]
    stmt = stmt.order_by(order).offset(offset).limit(limit)
    films = list((await session.execute(stmt)).scalars())
    marks = await _my_marks(session, user.id, films)
    return [_brief(film, marks) for film in films]


@router.get("/tmdb/{tmdb_id}", response_model=FilmCard)
async def tmdb_card(
    tmdb_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FilmCard:
    """Карточка фильма, которого ещё нет в каталоге.

    Данные берутся из TMDB и НЕ сохраняются: иначе база заполнялась бы всем,
    что кто-то просто открыл посмотреть. В каталог фильм попадает при первой
    отметке, как и раньше.
    """
    existing = (
        await session.execute(sa.select(Film).where(Film.tmdb_id == tmdb_id))
    ).scalar_one_or_none()
    if existing is not None:
        # Фильм уже завели — показываем полноценную карточку с рейтингом клуба.
        return await film_card(existing.id, user, session)

    try:
        payload = await get_tmdb().movie(tmdb_id)
    except TmdbError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"TMDB недоступен: {exc}") from exc

    fields = film_fields(payload)
    release = payload.get("release_date") or ""

    return FilmCard(
        id=None,
        tmdb_id=tmdb_id,
        title_ru=fields["title_ru"],
        title_orig=fields["title_orig"],
        year=int(release[:4]) if release[:4].isdigit() else None,
        poster_url=poster_url(fields["poster_path"]),
        genres=fields["genres"],
        directors=fields["directors"],
        in_catalog=False,
        # Отметок быть не может: фильма нет в каталоге, отмечать было нечего.
        my_interests=[],
        watched=False,
        runtime_min=fields["runtime_min"],
        overview=fields["overview"],
        trailer_key=fields["trailer_key"],
        ext_rating=fields["ext_rating"],
        ext_votes=fields["ext_votes"],
        # Внутренних данных нет: фильм ещё не в каталоге, отмечать его никто не мог.
        internal_rating=None,
        internal_votes=0,
        interested_count=0,
        reviews=[],
    )


@router.get("/{film_id}", response_model=FilmCard)
async def film_card(
    film_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FilmCard:
    film = await session.get(Film, film_id)
    if film is None or film.status == FilmStatus.HIDDEN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фильм не найден")

    settings = SettingsService(session)
    min_votes = int(await settings.get("internal_rating_min_votes"))

    interested_count = (
        await session.execute(
            sa.select(sa.func.count(sa.distinct(Interest.user_id))).where(
                Interest.film_id == film_id, Interest.revoked_at.is_(None)
            )
        )
    ).scalar_one()

    marks = await _my_marks(session, user.id, [film])

    rating_row = (
        await session.execute(
            sa.select(sa.func.avg(Feedback.film_rating), sa.func.count(Feedback.film_rating)).where(
                Feedback.film_id == film_id, Feedback.film_rating.is_not(None)
            )
        )
    ).one()
    avg, votes = rating_row

    reviews = [
        ReviewOut(
            author=author,
            rating=feedback.film_rating,
            text=feedback.review_text,
            created_at=feedback.created_at,
        )
        for feedback, author in await session.execute(
            sa.select(Feedback, User.display_name)
            .join(User, User.id == Feedback.user_id)
            .where(Feedback.film_id == film_id, Feedback.review_text.is_not(None))
            .order_by(Feedback.created_at.desc())
            .limit(20)
        )
    ]

    return FilmCard(
        **_brief(film, marks).model_dump(),
        runtime_min=film.runtime_min,
        overview=film.overview,
        trailer_key=film.trailer_key,
        ext_rating=film.ext_rating,
        ext_votes=film.ext_votes,
        internal_rating=round(float(avg), 2) if votes >= min_votes and avg is not None else None,
        internal_votes=votes,
        interested_count=interested_count,
        reviews=reviews,
    )

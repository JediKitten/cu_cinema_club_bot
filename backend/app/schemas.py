from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import FilmRequestStatus, InterestKind, UserRole


class UserOut(BaseModel):
    id: int
    display_name: str
    role: UserRole
    photo_url: str | None = None
    tg_username: str | None = None


class AuthOut(BaseModel):
    token: str
    user: UserOut


class TelegramAuthIn(BaseModel):
    init_data: str


class FilmBrief(BaseModel):
    """Карточка в списке. tmdb_id отдаём, чтобы фронт мог отметить фильм,
    которого ещё нет в базе: id будет присвоен при первой отметке."""

    id: int | None = None
    tmdb_id: int | None = None
    title_ru: str
    title_orig: str | None = None
    year: int | None = None
    poster_url: str | None = None
    genres: list[str] = Field(default_factory=list)
    in_catalog: bool = True


class FilmCard(FilmBrief):
    runtime_min: int | None = None
    overview: str | None = None
    trailer_key: str | None = None
    ext_rating: float | None = None
    ext_votes: int | None = None
    # Внутренний рейтинг скрыт, пока оценок меньше порога (§11).
    internal_rating: float | None = None
    internal_votes: int = 0
    # Публично видно только ЧИСЛО желающих, никогда не поимённый список (§11).
    interested_count: int = 0
    my_interests: list[InterestKind] = Field(default_factory=list)
    watched: bool = False
    reviews: list["ReviewOut"] = Field(default_factory=list)


class ReviewOut(BaseModel):
    author: str
    rating: int | None
    text: str | None
    created_at: datetime


class InterestIn(BaseModel):
    kind: InterestKind
    tmdb_id: int | None = None


class InterestOut(BaseModel):
    film: FilmBrief
    kinds: list[InterestKind]
    created_at: datetime
    expires_at: datetime | None = None


class FilmRequestIn(BaseModel):
    raw_title: str = Field(min_length=1, max_length=512)
    raw_year: int | None = Field(default=None, ge=1874, le=2100)
    note: str | None = Field(default=None, max_length=2000)


class FilmRequestOut(BaseModel):
    id: int
    raw_title: str
    raw_year: int | None
    note: str | None
    status: FilmRequestStatus
    resolution_comment: str | None
    created_at: datetime


class SettingOut(BaseModel):
    key: str
    value: Any
    type: str
    group: str
    label: str
    help: str | None = None
    min: float | None = None
    max: float | None = None
    affects_weights: bool = False


class SettingsPatch(BaseModel):
    values: dict[str, Any]


class RankRow(BaseModel):
    film_id: int
    title_ru: str
    title_orig: str | None
    year: int | None
    poster_url: str | None
    weight: float
    wishlist_count: int
    soon_count: int
    long_wait_count: int
    ext_rating: float | None
    ext_votes: int | None
    internal_rating: float | None
    internal_votes: int
    marginal_weight: float | None = None
    screening_history: list[dict] = Field(default_factory=list)


class RankingsOut(BaseModel):
    by_weight: list[RankRow]
    by_coverage: list[RankRow]


class SandboxIn(BaseModel):
    """Песочница весов (§13): пересчитать рейтинг с этими коэффициентами,
    ничего не сохраняя."""

    wishlist_base_weight: float | None = None
    wishlist_half_life_days: float | None = None
    wishlist_weight_floor: float | None = None
    soon_weight: float | None = None
    soon_ttl_days: int | None = None
    limit: int = Field(default=20, ge=1, le=100)


FilmCard.model_rebuild()

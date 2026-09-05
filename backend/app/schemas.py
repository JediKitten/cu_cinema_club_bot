from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import FilmRequestStatus, InterestKind, RoundStage, UserRole


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
    directors: list[str] = Field(default_factory=list)
    in_catalog: bool = True
    # Состояний три и они взаимоисключающие, поэтому список — либо пустой, либо
    # ровно из одного элемента. Здесь то, чем отметка ЯВЛЯЕТСЯ сейчас: у
    # истёкшего «Ближайшего» это уже «Желаемое».
    my_interests: list[InterestKind] = Field(default_factory=list)
    # Срок «Ближайшего» вышел — предлагаем поставить его заново (§4).
    can_renew_soon: bool = False
    soon_expires_at: datetime | None = None
    watched: bool = False


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
    # Не больше одного элемента: состояния взаимоисключающие.
    kinds: list[InterestKind] = Field(default_factory=list)
    expires_at: datetime | None = None
    can_renew_soon: bool = False
    watched: bool = False


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


# --- Цикл и шорт-лист (§2, §5) ---------------------------------------------


class SlotOut(BaseModel):
    id: int
    starts_at: datetime
    duration_min: int
    blocked: bool
    blocked_reason: str | None = None
    hall_name: str
    hall_capacity: int


class ShortlistItemOut(BaseModel):
    film_id: int
    position: int
    source: str
    film: FilmBrief


class RoundOut(BaseModel):
    id: int
    week_start: date
    stage: RoundStage
    low_activity: bool
    shortlist_locked_at: datetime | None = None
    published_at: datetime | None = None
    shortlist: list[ShortlistItemOut] = Field(default_factory=list)
    slots: list[SlotOut] = Field(default_factory=list)
    # Решение автопилота показывается рядом с ручным выбором как подсказка (§5).
    autopilot_film_ids: list[int] = Field(default_factory=list)


class OpenRoundIn(BaseModel):
    week_start: date | None = None


class ShortlistIn(BaseModel):
    film_ids: list[int] = Field(min_length=1)


class BlockSlotIn(BaseModel):
    blocked: bool
    reason: str | None = Field(default=None, max_length=500)


# --- Этап 2: голосование (§6) ----------------------------------------------


class BallotOut(BaseModel):
    """То, что видит пользователь на этапе 2: шорт-лист, вечера и свой выбор."""

    round_id: int
    week_start: date
    films: list[FilmBrief]
    slots: list[SlotOut]
    my_film_ids: list[int] = Field(default_factory=list)
    my_slot_ids: list[int] = Field(default_factory=list)


class VotesIn(BaseModel):
    film_ids: list[int] = Field(default_factory=list)


class AvailabilityIn(BaseModel):
    slot_ids: list[int] = Field(default_factory=list)


class MatrixCell(BaseModel):
    film_id: int
    slot_id: int
    count: int


class MatrixOut(BaseModel):
    films: list[FilmBrief]
    slots: list[SlotOut]
    cells: list[MatrixCell]
    # Маргинальные суммы: популярность фильма и загруженность вечера (§6).
    film_votes: dict[int, int] = Field(default_factory=dict)
    slot_free: dict[int, int] = Field(default_factory=dict)
    voters_without_evening: int = 0


# --- Этап 3: расписание и подтверждения (§7) --------------------------------


class ScreeningOut(BaseModel):
    id: int
    film: FilmBrief
    slot: SlotOut
    status: str
    expected_attendance: int | None = None
    cancel_reason: str | None = None
    # Состояние текущего пользователя по этому показу.
    my_state: str | None = None
    my_place_in_queue: int | None = None
    confirmed: int = 0
    capacity: int = 0
    # Голосовал за фильм — значит, показ его касается и приглашение было.
    invited: bool = False


class ScheduleOut(BaseModel):
    round_id: int
    week_start: date
    stage: str
    published: bool
    screenings: list[ScreeningOut] = Field(default_factory=list)


class AssignIn(BaseModel):
    film_id: int
    slot_id: int


class MoveIn(BaseModel):
    slot_id: int


class CancelIn(BaseModel):
    # Комментарий обязателен: он уходит всем, кто собирался прийти (§7).
    reason: str = Field(min_length=3, max_length=500)


class ConfirmOut(BaseModel):
    screening_id: int
    state: str
    place_in_queue: int | None = None
    confirmed: int
    capacity: int

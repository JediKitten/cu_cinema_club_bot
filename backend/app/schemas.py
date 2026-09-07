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
    # Пускать ли внутрь: на время закрытой беты нужен код-приглашение.
    access: bool = True


class AuthOut(BaseModel):
    token: str
    user: UserOut


class TelegramAuthIn(BaseModel):
    init_data: str


# --- Бета-доступ по кодам ----------------------------------------------------


class InviteIn(BaseModel):
    """Сколько кодов выдать и на сколько человек каждый."""

    count: int = Field(default=1, ge=1, le=100)
    max_activations: int = Field(default=1, ge=1, le=1000)
    note: str | None = Field(default=None, max_length=200)


class RedeemIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class BetaIn(BaseModel):
    enabled: bool


class InviteeOut(BaseModel):
    user_id: int
    display_name: str


class InviteCodeOut(BaseModel):
    id: int
    code: str
    max_activations: int
    used: int
    left: int
    note: str | None = None
    created_at: datetime
    created_by: int
    created_by_name: str
    invitees: list[InviteeOut] = Field(default_factory=list)


class PersonRowOut(BaseModel):
    """Строка вкладки «Пользователи» у главного админа."""

    id: int
    display_name: str
    tg_username: str | None = None
    role: UserRole
    created_at: datetime
    has_access: bool
    invite_code: str | None = None
    invited_by: str | None = None


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
    # Рейтинг клуба по пятибалльной шкале с половинками. Рядом всегда стоит
    # число оценивших — оно честнее порога «показывать с пяти оценок».
    internal_rating: float | None = None
    internal_votes: int = 0
    # Своя оценка: 0.5..5 или ничего.
    my_rating: float | None = None
    # Публично видно только ЧИСЛО желающих, никогда не поимённый список (§11).
    interested_count: int = 0
    # Кто позвал на этот фильм по ссылке — подпись в карточке.
    invited_by: str | None = None
    reviews: list["ReviewOut"] = Field(default_factory=list)


class ReviewOut(BaseModel):
    author: str
    rating: int | None
    text: str | None
    created_at: datetime


class DeckCard(BaseModel):
    """Карточка ленты: всё, что нужно решить за секунду."""

    id: int
    title_ru: str
    title_orig: str | None = None
    year: int | None = None
    poster_url: str | None = None
    genres: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    runtime_min: int | None = None
    overview: str | None = None
    ext_rating: float | None = None
    internal_rating: float | None = None
    internal_votes: int = 0


class DeckOut(BaseModel):
    cards: list[DeckCard] = Field(default_factory=list)
    # Сколько ещё не размечено: лента должна уметь кончиться.
    left: int = 0


class RatingIn(BaseModel):
    """Оценка в звёздах: 0.5..5 с шагом в половину. None снимает оценку."""

    stars: float | None = Field(default=None, ge=0.5, le=5)


class RatingOut(BaseModel):
    film_id: int
    my_rating: float | None = None
    internal_rating: float | None = None
    internal_votes: int = 0


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
    # Сколько раз фильм попадал в шорт-лист и не был назначен (§14).
    shortlist_misses: int = 0
    marginal_weight: float | None = None
    screening_history: list[dict] = Field(default_factory=list)


class FilmStatsOut(BaseModel):
    """Разрез по фильму для админа (§14)."""

    film_id: int
    weight: float
    wishlist_count: int
    soon_count: int
    long_wait_count: int
    long_wait_days: int
    shortlist_misses: int
    shortlist_hits: int
    internal_rating: float | None = None
    internal_votes: int = 0
    dynamics: list[dict] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)


class PersonOut(BaseModel):
    user_id: int
    display_name: str
    detail: str | None = None


class ScreeningStatsOut(BaseModel):
    """Разрез по сеансу (§14): до показа — кто придёт, после — кто пришёл."""

    screening_id: int
    starts_at: datetime
    capacity: int
    confirmed: int
    fill_rate: float
    waitlist: list[PersonOut] = Field(default_factory=list)
    attended: list[PersonOut] = Field(default_factory=list)
    no_shows: list[PersonOut] = Field(default_factory=list)
    cancelled: int = 0
    late_cancels: int = 0
    started: bool = False
    low_attendance_warning: bool = False
    min_attendance: int = 0
    film_rating: float | None = None
    film_rating_votes: int = 0
    org_rating: float | None = None
    org_rating_votes: int = 0


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


# --- Профили, друзья и лента -------------------------------------------------


class PersonBrief(BaseModel):
    id: int
    display_name: str
    tg_username: str | None = None
    photo_url: str | None = None
    # Как мы связаны с этим человеком: взаимно, я на него, он на меня.
    friends: bool = False
    following: bool = False
    follower: bool = False


class FeedItemOut(BaseModel):
    """Событие ленты: оценка, отзыв, отметка или просмотр."""

    kind: str
    at: datetime
    user_id: int
    user_name: str
    user_photo: str | None = None
    film_id: int
    film_title: str
    film_year: int | None = None
    film_poster: str | None = None
    # Оценка в звёздах: 0.5..5.
    rating: float | None = None
    text: str | None = None


class ProfileOut(BaseModel):
    id: int
    display_name: str
    tg_username: str | None = None
    photo_url: str | None = None
    role: UserRole
    joined_at: datetime
    favourites: list[FilmBrief] = Field(default_factory=list)
    marks: int = 0
    watched: int = 0
    ratings: int = 0
    average_rating: float | None = None
    # Распределение оценок: десять чисел, от половины звезды до пяти.
    ratings_by_score: list[int] = Field(default_factory=list)
    friends: int = 0
    is_me: bool = False
    relation_friends: bool = False
    relation_following: bool = False
    relation_follower: bool = False
    recent: list[FeedItemOut] = Field(default_factory=list)


class CircleOut(BaseModel):
    friends: list[PersonBrief] = Field(default_factory=list)
    following: list[PersonBrief] = Field(default_factory=list)
    followers: list[PersonBrief] = Field(default_factory=list)


class FavouriteRef(BaseModel):
    """Фильм из каталога — по id, найденный в TMDB — по tmdb_id.

    Двумя полями, а не одним списком id: фильма из TMDB в каталоге ещё нет,
    и он заводится в момент, когда его выбрали.
    """

    film_id: int | None = None
    tmdb_id: int | None = None


class FavouritesIn(BaseModel):
    films: list[FavouriteRef] = Field(default_factory=list, max_length=4)



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
    # Окно, в котором шорт-лист собирают руками. Интерфейс по нему объясняет,
    # почему кнопки не нажимаются, вместо того чтобы молча их гасить.
    shortlist_window_opens_at: datetime | None = None
    shortlist_window_closes_at: datetime | None = None
    shortlist_window_open: bool = False


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


class Assignment(BaseModel):
    film_id: int
    slot_id: int
    expected: int


class MatrixOut(BaseModel):
    films: list[FilmBrief]
    slots: list[SlotOut]
    cells: list[MatrixCell]
    # Маргинальные суммы: популярность фильма и загруженность вечера (§6).
    film_votes: dict[int, int] = Field(default_factory=dict)
    slot_free: dict[int, int] = Field(default_factory=dict)
    voters_without_evening: int = 0
    # Закрытые вечера: назначать на них нельзя, но видеть, скольких мы теряем,
    # администратору нужно — иначе блокировка выглядит бесплатной.
    blocked_slots: list[SlotOut] = Field(default_factory=list)
    # Решение автопилота рядом с ручным, в теневом режиме (§5, §6).
    autopilot: list[Assignment] = Field(default_factory=list)
    manual: list[Assignment] = Field(default_factory=list)
    autopilot_expected: int = 0
    manual_expected: int = 0


# --- Этап 3: расписание и подтверждения (§7) --------------------------------


class ScreeningOut(BaseModel):
    id: int
    film: FilmBrief
    slot: SlotOut
    status: str
    expected_attendance: int | None = None
    cancel_reason: str | None = None
    # Назначено вручную, вне алгоритма.
    is_manual: bool = False
    # Подпись к событию без фильма: «ждите анонса».
    note: str | None = None
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
    # Есть ли что показать в соседних неделях — по ним рисуются стрелки.
    has_prev: bool = False
    has_next: bool = False
    # Идёт голосование на другую неделю — ведём туда явной подсказкой.
    voting_week: date | None = None


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


# --- Этап 4: присутствие и обратная связь (§8) ------------------------------


class CodeOut(BaseModel):
    """Код для экрана в зале. Живёт секунды, поэтому отдаём и остаток."""

    screening_id: int
    code: str
    valid_for: int
    rotates_every: int
    window_open: bool
    attendees: int


class MarkCodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


class AttendeeOut(BaseModel):
    user_id: int
    display_name: str
    method: str
    marked_at: datetime


class OrgRating(BaseModel):
    sound: int | None = Field(default=None, ge=1, le=5)
    picture: int | None = Field(default=None, ge=1, le=5)
    hall: int | None = Field(default=None, ge=1, le=5)
    time: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackIn(BaseModel):
    # Обязательна только отметка присутствия, форма — нет (§8).
    film_rating: int | None = Field(default=None, ge=1, le=10)
    review_text: str | None = Field(default=None, max_length=2000)
    org: OrgRating | None = None


class FeedbackOut(BaseModel):
    screening_id: int
    film: FilmBrief
    attended: bool
    film_rating: int | None = None
    review_text: str | None = None
    org: OrgRating | None = None


# --- Аналитика (§14) --------------------------------------------------------


class FunnelStep(BaseModel):
    week_start: date
    stage: str
    interested: int
    voted: int
    confirmed: int
    attended: int


class OverviewOut(BaseModel):
    rounds: int
    screenings_held: int
    screenings_cancelled: int
    average_attendance: float
    hall_fill_rate: float
    active_users: int
    # Подтвердил и не пришёл — доля от подтверждений на прошедших показах.
    no_show_rate: float
    late_cancels: int
    # Доля отменённых сеансов от всех назначенных.
    cancelled_share: float = 0.0
    by_weekday: dict[str, float] = Field(default_factory=dict)
    long_wait_films: list[dict] = Field(default_factory=list)
    audience_by_week: list[dict] = Field(default_factory=list)
    no_show_users: list[dict] = Field(default_factory=list)
    # Отток на истечении «Ближайшего»: {expired_marks, people, lapsed}.
    soon_churn: dict = Field(default_factory=dict)


class AnalyticsOut(BaseModel):
    funnel: list[FunnelStep] = Field(default_factory=list)
    overview: OverviewOut
    top_rated: list[dict] = Field(default_factory=list)


class PastScreeningOut(BaseModel):
    screening_id: int
    film_id: int
    title: str
    year: int | None
    poster_url: str | None
    starts_at: datetime
    status: str
    expected: int | None
    came: int
    rating: float | None


# --- Ручные события и роли --------------------------------------------------


class EventIn(BaseModel):
    """Событие вне цикла: фильм необязателен, время любое."""

    starts_at: datetime
    film_id: int | None = None
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    duration_min: int = Field(default=180, ge=30, le=600)


class EventPatch(BaseModel):
    """Правка события. Присланы только изменённые поля: отсутствие ключа и None
    здесь значат разное — снять фильм с анонса и не трогать его."""

    starts_at: datetime | None = None
    film_id: int | None = None
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    duration_min: int | None = Field(default=None, ge=30, le=600)


class EventOut(BaseModel):
    id: int
    starts_at: datetime
    duration_min: int
    film_id: int | None = None
    film: FilmBrief | None = None
    title: str | None = None
    note: str | None = None
    confirmed: int = 0


class CancelEventIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RevealIn(BaseModel):
    film_id: int


class TeamMember(BaseModel):
    id: int
    display_name: str
    tg_username: str | None = None
    role: UserRole


class RoleIn(BaseModel):
    role: UserRole


# --- Пригласительные ссылки -------------------------------------------------


class InviteOut(BaseModel):
    """Ссылка на фильм и то, что уже принесли прежние приглашения."""

    link: str
    film_id: int
    invited: int = 0
    accepted: int = 0


class ReferralStatsOut(BaseModel):
    invited: int
    accepted: int

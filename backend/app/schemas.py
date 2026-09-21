from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    DiscussionSkip,
    FilmRequestStatus,
    InterestKind,
    RoundStage,
    UserRole,
)


class UserOut(BaseModel):
    id: int
    display_name: str
    role: UserRole
    photo_url: str | None = None
    tg_username: str | None = None
    # Совместимость с приложением, залёгшим в кэше Telegram. Вход по кодам
    # убран, но у старой сборки экран «введите код» показывался именно по
    # отсутствию этого поля — и, перестав его присылать, мы заперли снаружи
    # всех, к кому новая сборка ещё не доехала. Поле можно снять, когда
    # старых клиентов не останется: оно всегда true и ничего не решает.
    access: bool = True


class AuthOut(BaseModel):
    token: str
    user: UserOut


class TelegramAuthIn(BaseModel):
    init_data: str


class PersonRowOut(BaseModel):
    """Строка вкладки «Люди» у главного админа."""

    id: int
    display_name: str
    tg_username: str | None = None
    role: UserRole
    created_at: datetime


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
    # Оценки источников по отдельности: каталог наполняется из двух, и одну
    # подписывать именем другой нельзя.
    kp_rating: float | None = None
    kp_votes: int | None = None
    tmdb_rating: float | None = None
    tmdb_votes: int | None = None
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
    kp_rating: float | None = None
    tmdb_rating: float | None = None
    internal_rating: float | None = None
    internal_votes: int = 0
    # Почему карточка здесь: рекомендация без объяснения выглядит случайной.
    reason: str | None = None


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
    visit_rating: float | None = None
    visit_rating_votes: int = 0
    discussion_rating: float | None = None
    discussion_rating_votes: int = 0


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


class AttendanceStats(BaseModel):
    """Посещаемость показов клуба (блок в профиле)."""

    came: int = 0
    planned: int = 0
    # Доля дошедших от собиравшихся. Пусто, пока ходить было не на что.
    ratio: float | None = None
    last_at: datetime | None = None
    last_film: str | None = None


class CustomAchievementIn(BaseModel):
    """Именная ачивка: админ придумывает её под конкретного человека."""

    user_id: int
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=200)
    tier: Literal["bronze", "silver", "gold", "platinum"] = "gold"


class CustomAchievementOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    title: str
    description: str
    tier: str
    earned_at: datetime


class AchievementStepOut(BaseModel):
    """Ступень цели — строка во вкладке своей редкости."""

    tier: str
    title: str
    description: str
    target: int
    progress: int
    earned_at: datetime | None = None


class AchievementGroupOut(BaseModel):
    """Одна цель со ступенями: держится высшая достигнутая.

    Без «осталось три до серебра» бейдж выглядит случайной наградой, а не целью,
    поэтому прогресс к следующей ступени едет вместе с полученной.
    """

    group: str
    label: str
    secret: bool = False
    # Придумана админом под конкретного человека, а не взята из реестра.
    custom: bool = False
    # Секретная, которую смотрящий сам не открыл: название и условие скрыты,
    # трофей виден.
    hidden: bool = False
    # Что уже получено: bronze | silver | gold | platinum. Пусто — ещё ничего.
    tier: str | None = None
    emoji: str = ""
    title: str = ""
    description: str = ""
    earned_at: datetime | None = None
    # Куда расти. Пусто, если взята платина.
    next_title: str | None = None
    next_description: str | None = None
    next_tier: str | None = None
    progress: int = 0
    target: int = 0
    # Вся лестница: вкладка уровня показывает все его ступени, а не только
    # достижимую следующую.
    steps: list[AchievementStepOut] = Field(default_factory=list)


class AchievementsOut(BaseModel):
    """Четыре числа для профиля и разбор по целям."""

    bronze: int = 0
    silver: int = 0
    gold: int = 0
    platinum: int = 0
    # Сколько секретных ещё не найдено, по уровням: у каждой вкладки свой
    # счётчик. Названия и условия не раскрываем — в этом весь их смысл.
    secrets_left: dict[str, int] = Field(default_factory=dict)
    groups: list[AchievementGroupOut] = Field(default_factory=list)


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
    attendance: AttendanceStats = Field(default_factory=AttendanceStats)
    achievements: AchievementsOut = Field(default_factory=AchievementsOut)
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
    # Неделя объявлена англоязычной: показ пройдёт в оригинале без дубляжа.
    in_english: bool = False
    # Когда шорт-лист можно собирать руками. Интерфейс по этому объясняет,
    # почему кнопки не нажимаются, вместо того чтобы молча их гасить.
    shortlist_window_opens_at: datetime | None = None
    # Когда список соберётся сам, если админ ничего не сделает. Не граница
    # запрета: после автопилота править можно, пока не опубликовано.
    shortlist_autopilot_at: datetime | None = None
    shortlist_window_open: bool = False


class OpenRoundIn(BaseModel):
    week_start: date | None = None


class RoundLanguageIn(BaseModel):
    in_english: bool


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
    # Неделя объявлена англоязычной. Голосуя, человек должен это знать:
    # язык решает, пойдёт он или нет, не хуже самого фильма.
    in_english: bool = False


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
    # Показ идёт на английском — это видно и в расписании, и в ачивках.
    in_english: bool = False
    # Своя регистрация у вуза: ссылку показываем записавшимся.
    registration_url: str | None = None
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


class SurveyAnswerOut(BaseModel):
    user_id: int
    display_name: str
    visit: int | None = None
    film: int | None = None
    discussion: int | None = None
    discussion_skip: DiscussionSkip | None = None
    comment: str | None = None
    answered_at: datetime


class SurveyOut(BaseModel):
    """Опрос по одному показу: цифры для отчёта и ответы поимённо."""

    screening_id: int
    starts_at: datetime
    title: str
    attended: int
    answered: int
    visit_avg: float | None = None
    film_avg: float | None = None
    discussion_avg: float | None = None
    discussion_absent: int = 0
    discussion_unsure: int = 0
    answers: list[SurveyAnswerOut] = Field(default_factory=list)


class FeedbackIn(BaseModel):
    """Опрос после показа. Обязательна только отметка присутствия, форма — нет
    (§8): заполненная из-под палки, она собирала бы вежливые пятёрки."""

    # Оценки — те же полубаллы, что и у фильмов: 1..10 это 0,5..5 звёзд.
    visit_rating: int | None = Field(default=None, ge=1, le=10)
    film_rating: int | None = Field(default=None, ge=1, le=10)
    discussion_rating: int | None = Field(default=None, ge=1, le=10)
    # «Не был» и «затрудняюсь ответить» — разные ответы, и оба честные.
    discussion_skip: DiscussionSkip | None = None
    review_text: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    screening_id: int
    # Пусто у события без фильма: про кино тогда не спрашиваем.
    film: FilmBrief | None = None
    attended: bool
    visit_rating: int | None = None
    film_rating: int | None = None
    discussion_rating: int | None = None
    discussion_skip: DiscussionSkip | None = None
    review_text: str | None = None
    # Фильм этот человек уже оценил (в каталоге, в ленте или после прошлого
    # показа) — второй раз спрашивать незачем, оценка у фильма одна.
    film_already_rated: bool = False


# --- Турниры (расширение по просьбе клуба) ----------------------------------


class TournamentOptionOut(BaseModel):
    id: int
    seed: int
    title: str
    subtitle: str | None = None
    image_url: str | None = None
    film_id: int | None = None


class TournamentMatchOut(BaseModel):
    id: int
    round_no: int
    position: int
    option_a: TournamentOptionOut | None = None
    option_b: TournamentOptionOut | None = None
    opens_at: datetime
    closes_at: datetime
    # Мой голос виден всегда, чужие — только после закрытия этапа: счёт
    # на глазах у голосующих подталкивает к большинству (§11).
    my_option_id: int | None = None
    votes_a: int | None = None
    votes_b: int | None = None
    winner_option_id: int | None = None


class TournamentRoundOut(BaseModel):
    round_no: int
    name: str
    closed: bool
    matches: list[TournamentMatchOut] = Field(default_factory=list)


class TournamentOut(BaseModel):
    id: int
    title: str
    description: str | None = None
    status: str
    current_round: int
    stage_hours: int
    options_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    winner: TournamentOptionOut | None = None
    rounds: list[TournamentRoundOut] = Field(default_factory=list)
    left_to_vote: int = 0
    closes_at: datetime | None = None


class TournamentBrief(BaseModel):
    """Строка архива и содержимое плашки: без сетки целиком."""

    id: int
    title: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TournamentIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class TournamentOptionIn(BaseModel):
    """Либо фильм из каталога, либо своя карточка."""

    title: str = Field(default="", max_length=120)
    subtitle: str | None = Field(default=None, max_length=200)
    image_url: str | None = Field(default=None, max_length=1000)
    film_id: int | None = None


class TournamentOptionsIn(BaseModel):
    options: list[TournamentOptionIn] = Field(default_factory=list, max_length=32)


class TournamentVoteIn(BaseModel):
    match_id: int
    option_id: int


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


class ExportPasswordOut(BaseModel):
    """Состояние пароля на /analytics. Самого пароля тут нет и быть не может —
    в базе лежит только хеш."""

    is_set: bool
    updated_at: datetime | None = None
    updated_by: str | None = None


class ExportPasswordIn(BaseModel):
    # Пустая строка снимает пароль и выключает выгрузку в боте.
    password: str = ""


class PastScreeningOut(BaseModel):
    screening_id: int
    film_id: int
    title: str
    year: int | None
    # Про смотрящего: был ли он тут и ответил ли на опрос. По ним рисуется
    # кнопка «пройти опрос» — иначе идти с напоминания было бы некуда.
    i_attended: bool = False
    i_answered: bool = False
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
    # Показ в оригинале: свойство сеанса, а не фильма.
    in_english: bool = False
    # Куда записаться помимо клуба — вуз ведёт свой учёт.
    registration_url: str | None = Field(default=None, max_length=500)


class EventPatch(BaseModel):
    """Правка события. Присланы только изменённые поля: отсутствие ключа и None
    здесь значат разное — снять фильм с анонса и не трогать его."""

    starts_at: datetime | None = None
    film_id: int | None = None
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    duration_min: int | None = Field(default=None, ge=30, le=600)
    in_english: bool | None = None
    registration_url: str | None = Field(default=None, max_length=500)
    # Не поле события, а указание: оставить ли записи при переносе времени.
    keep_confirmations: bool = False


class BroadcastIn(BaseModel):
    """Рассылка от лица бота: текст и кому."""

    text: str = Field(min_length=1, max_length=3500)
    audience: Literal["all", "screening"] = "all"
    screening_id: int | None = None


class BroadcastOut(BaseModel):
    recipients: int
    audience: str
    screening_id: int | None = None


class BroadcastTarget(BaseModel):
    """Показ, которому можно написать."""

    id: int
    starts_at: datetime
    title: str
    signed_up: int


class AudienceOut(BaseModel):
    """Сколько человек получат сообщение — до того, как его отправят."""

    recipients: int


class EventOut(BaseModel):
    id: int
    starts_at: datetime
    duration_min: int
    film_id: int | None = None
    film: FilmBrief | None = None
    title: str | None = None
    note: str | None = None
    in_english: bool = False
    registration_url: str | None = None
    # Ручное событие или показ, назначенный циклом: у второго правится не всё.
    is_manual: bool = True
    confirmed: int = 0
    # Шорт-лист недели — у показа из цикла. Заменить фильм можно только
    # на один из них, и выбирать администратор должен из списка, а не гадать,
    # что сервер примет.
    shortlist: list[FilmBrief] = Field(default_factory=list)


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


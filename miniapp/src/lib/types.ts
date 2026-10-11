/**
 * Модели представления (view-models), которые потребляют экраны.
 *
 * В проде типы ответов генерируются из OpenAPI-схемы бэкенда
 * (openapi-typescript → src/api/schema.d.ts). Эти интерфейсы — то, что
 * нужно интерфейсу; адаптеры в src/lib/api.ts переводят ответы API в них.
 * Если поля в схеме называются так же — интерфейсы можно заменить на
 * `components['schemas'][...]` напрямую.
 */

/** Отметка интереса. `wish_expired` — «Ближайшее» истекло и стало «Желаемым». */
export type Mark = 'none' | 'wish' | 'soon' | 'wish_expired'

export type TabId = 'catalog' | 'feed' | 'schedule' | 'profile'

export type Role = 'user' | 'moderator' | 'admin' | 'superadmin'

export interface FilmShort {
  id: number
  title: string
  originalTitle?: string
  year?: number
  directors: string[]
  posterUrl?: string
}

export interface FilmRatings {
  /** Рейтинг клуба, 0.5–5 */
  club?: number
  clubCount: number
  /** Кинопоиск, 0–10 */
  kp?: number
  kpVotes?: number
  /** TMDB, 0–10 */
  tmdb?: number
  tmdbVotes?: number
  /** Сколько участников хотят посмотреть */
  wantCount: number
}

export interface Review {
  id: number
  author: string
  avatarUrl?: string
  rating?: number
  text: string
}

export interface Film extends FilmShort {
  runtimeMin?: number
  genres: string[]
  overview?: string
  trailerUrl?: string
  mark: Mark
  seen: boolean
  myRating?: number
  ratings: FilmRatings
  reviews: Review[]
  /** Найден в TMDB, в каталоге клуба ещё нет */
  fromTmdb?: boolean
  /** Пришёл по ссылке друга: имя пригласившего */
  invitedBy?: string
}

export interface FeedItem extends Film {
  /** Причина показа одной строкой: «Друг оценил на 4,5» */
  reason?: string
}

export type SortKey = 'kp' | 'tmdb' | 'club' | 'want' | 'year'

export type WeekStage = 'collect' | 'vote' | 'schedule' | 'shows'

export interface Evening {
  id: number
  startsAt: string // ISO
  place: string
  closed?: boolean
}

export interface Ballot {
  weekStart: string // ISO-дата понедельника
  english?: boolean
  films: FilmShort[]
  evenings: Evening[]
  selectedFilmIds: number[]
  selectedEveningIds: number[]
  /** До какого момента открыто голосование */
  closesAt: string
}

export type ShowState = 'upcoming' | 'live' | 'past' | 'cancelled'
export type MyShowStatus = 'none' | 'going' | 'queued' | 'attended' | 'missed'

export interface Show {
  id: number
  film?: FilmShort
  /** Заголовок события без фильма */
  title?: string
  note?: string
  startsAt: string
  place: string
  capacity: number
  going: number
  queueLength: number
  /** Моё место в очереди, если в очереди */
  queuePosition?: number
  state: ShowState
  myStatus: MyShowStatus
  english?: boolean
  registrationUrl?: string
  /** Ссылка на .ics с напоминанием за 2 часа */
  calendarUrl?: string
  cancelReason?: string
}

export interface Week {
  start: string // ISO понедельника
  stage: WeekStage
  hasPrev: boolean
  hasNext: boolean
  /** Если голосование идёт на другую неделю — её начало */
  votingWeekStart?: string
}

export interface ScheduleWeek {
  week: Week
  ballot?: Ballot
  shows: Show[]
}

export interface SurveyAnswers {
  overall?: number
  film?: number
  discussion?: number | 'absent' | 'unsure'
  comment: string
}

export interface Survey {
  show: Show
  ticketNo: number
  /** Скрыть вопрос про фильм: уже оценён или у события нет фильма */
  hideFilmQuestion: boolean
  answers: SurveyAnswers
}

export interface Achievements {
  bronze: number
  silver: number
  gold: number
  platinum: number
  total: number
}

export interface Profile {
  id: number
  /** Свой профиль: двери в списки, меню, правка «Любимого» */
  isMe: boolean
  /** Отношение смотрящего к этому человеку (в чужом профиле) */
  relation: { friends: boolean; following: boolean; follower: boolean }
  name: string
  username?: string
  avatarUrl?: string
  role: Role
  counts: { marks: number; seen: number; friends: number }
  /** 10 корзин: 0,5 … 5 звёзд */
  ratingHistogram: number[]
  ratingAvg?: number
  favorites: FilmShort[]
  achievements: Achievements
  attendance?: { attended: number; planned: number; missed: number; percent: number }
  pendingRequests: number
  /** Ответ сервера целиком — для экранов, перенесённых из прежней версии (ачивки) */
  raw: import('../legacy/types').Profile
}

import * as server from '../legacy/api'
import type {
  FilmBrief as ServerFilm,
  FilmCard as ServerFilmCard,
  Profile as ServerProfile,
  Screening as ServerScreening,
} from '../legacy/types'
import type {
  Ballot, FeedItem, Film, FilmShort, Mark, MyShowStatus, Profile, ScheduleWeek, Show, SortKey, Survey,
  SurveyAnswers, WeekStage,
} from './types'

/**
 * Слой данных экранов редизайна.
 *
 * Экраны говорят на своих моделях (./types), сервер — на схемах API
 * (legacy/api.gen.ts, генерируются из бэкенда). Здесь одно переводится
 * в другое; сами запросы, вход по initData, таймауты и русские тексты
 * ошибок — в legacy/api.ts, общем для старых и новых экранов.
 */

export { ApiError } from '../legacy/api'

export const PAGE_SIZE = server.CATALOG_PAGE

// ---------- фильмы ----------

/**
 * Фильм из поиска TMDB ещё не в каталоге клуба — у него нет нашего id.
 * Экраны адресуют фильм одним числом, поэтому такой получает отрицательный:
 * -tmdb_id. Дальше id < 0 значит «спросить TMDB» и «завести при отметке».
 */
const tmdbKey = (tmdbId: number) => -tmdbId
const isTmdbKey = (id: number) => id < 0

/** Сервер для отметок и «Смотрел» принимает фильм целиком: по нему он
 *  решает, отмечать ли по нашему id или завести карточку из TMDB. */
const known = new Map<number, ServerFilm>()

function keyOf(film: ServerFilm): number {
  return film.id ?? tmdbKey(film.tmdb_id ?? 0)
}

function remember(film: ServerFilm): number {
  const key = keyOf(film)
  known.set(key, film)
  return key
}

function briefFor(id: number): ServerFilm {
  const film = known.get(id)
  if (film) return film
  // Карточку открыли по ссылке, не проходя через список, — хватит id.
  return isTmdbKey(id)
    ? stubFilm({ id: null, tmdb_id: -id })
    : stubFilm({ id, tmdb_id: null })
}

function stubFilm(ids: { id: number | null; tmdb_id: number | null }): ServerFilm {
  return {
    ...ids,
    title_ru: '',
    title_orig: null,
    year: null,
    poster_url: null,
    genres: [],
    directors: [],
    in_catalog: ids.id !== null,
    my_interests: [],
    can_renew_soon: false,
    soon_expires_at: null,
    watched: false,
  }
}

/** Отметка экрана из того, что знает сервер. «Ближайшее», истёкшее в
 *  «Желаемое», сервер помечает can_renew_soon — тогда рядом «Снова в ближайшее». */
export function markOf(film: Pick<ServerFilm, 'my_interests' | 'can_renew_soon'>): Mark {
  const kind = film.my_interests[0]
  if (kind === 'soon') return 'soon'
  if (kind === 'wishlist') return film.can_renew_soon ? 'wish_expired' : 'wish'
  return 'none'
}

export function shortOf(film: ServerFilm): FilmShort {
  return {
    id: remember(film),
    title: film.title_ru,
    originalTitle: film.title_orig && film.title_orig !== film.title_ru ? film.title_orig : undefined,
    year: film.year ?? undefined,
    directors: film.directors,
    posterUrl: film.poster_url ?? undefined,
  }
}

function rowOf(film: ServerFilm): Film {
  return {
    ...shortOf(film),
    genres: film.genres,
    mark: markOf(film),
    seen: film.watched,
    ratings: { clubCount: 0, wantCount: 0 },
    reviews: [],
    fromTmdb: !film.in_catalog,
  }
}

function cardOf(card: ServerFilmCard): Film {
  return {
    ...rowOf(card),
    runtimeMin: card.runtime_min ?? undefined,
    overview: card.overview ?? undefined,
    trailerUrl: card.trailer_key ? `https://www.youtube.com/watch?v=${card.trailer_key}` : undefined,
    myRating: card.my_rating ?? undefined,
    invitedBy: card.invited_by ?? undefined,
    ratings: {
      club: card.internal_rating ?? undefined,
      clubCount: card.internal_votes,
      kp: card.kp_rating ?? undefined,
      kpVotes: card.kp_votes ?? undefined,
      tmdb: card.tmdb_rating ?? undefined,
      tmdbVotes: card.tmdb_votes ?? undefined,
      wantCount: card.interested_count,
    },
    // Отзывы пишут в форме после показа — десятибалльной; на экране звёзды.
    reviews: card.reviews.map((review, index) => ({
      id: index,
      author: review.author,
      rating: review.rating != null ? review.rating / 2 : undefined,
      text: review.text ?? '',
    })),
  }
}

const SORT_PARAM: Record<SortKey, string> = {
  kp: 'kp',
  tmdb: 'tmdb',
  club: 'club',
  want: 'wanted',
  year: 'year',
}

export async function getCatalog(params: { query: string; sort: SortKey; limit: number }): Promise<{ items: Film[]; hasMore: boolean }> {
  if (params.query.trim().length >= 2) {
    const found = await server.searchFilms(params.query.trim())
    return { items: found.map(rowOf), hasMore: false }
  }
  const items = await server.browseFilms(SORT_PARAM[params.sort], 0, params.limit)
  return { items: items.map(rowOf), hasMore: items.length === params.limit }
}

export async function getFilm(id: number): Promise<Film> {
  const card = isTmdbKey(id) ? await server.getTmdbFilm(-id) : await server.getFilm(id)
  // Фильм из TMDB, только что заведённый отметкой, получил наш id —
  // запоминаем под обоими ключами, чтобы следующие действия шли по нему.
  known.set(id, card)
  return cardOf(card)
}

/** Перевод отметки экрана в вызов сервера. Возвращает фильм таким, каким
 *  его теперь знает сервер: у фильма из TMDB после первой отметки появляется id. */
export async function setMark(filmId: number, mark: Mark): Promise<void> {
  const film = briefFor(filmId)
  if (mark === 'none') {
    if (film.id !== null) await server.removeInterest(film.id)
    return
  }
  const state = await server.addInterest(film, mark === 'soon' ? 'soon' : 'wishlist')
  known.set(filmId, state.film)
}

export async function setSeen(filmId: number, seen: boolean): Promise<void> {
  const state = await server.setWatched(briefFor(filmId), seen)
  known.set(filmId, state.film)
}

export async function rateFilm(filmId: number, rating: number | undefined): Promise<void> {
  const film = briefFor(filmId)
  if (film.id === null) throw new server.ApiError(409, 'Сначала отметьте фильм — тогда его можно оценить')
  await server.rateFilm(film.id, rating ?? null)
}

// ---------- лента ----------

export async function getFeed(): Promise<FeedItem[]> {
  const deck = await server.getDeck()
  return deck.cards.map((card) => {
    const brief: ServerFilm = {
      ...stubFilm({ id: card.id, tmdb_id: null }),
      title_ru: card.title_ru,
      title_orig: card.title_orig,
      year: card.year,
      poster_url: card.poster_url,
      genres: card.genres,
      directors: card.directors,
    }
    return {
      ...rowOf(brief),
      runtimeMin: card.runtime_min ?? undefined,
      overview: card.overview ?? undefined,
      reason: card.reason ?? undefined,
      ratings: {
        club: card.internal_rating ?? undefined,
        clubCount: card.internal_votes,
        kp: card.kp_rating ?? undefined,
        tmdb: card.tmdb_rating ?? undefined,
        wantCount: 0,
      },
    }
  })
}

/** Свайп в ленте: right — в «Желаемое», left — «Не моё» (больше не показывать). */
export async function swipeFeed(filmId: number, direction: 'left' | 'right'): Promise<void> {
  if (direction === 'right') await server.addInterest(briefFor(filmId), 'wishlist')
  else await server.skipFilm(filmId)
}

// ---------- расписание ----------

const STAGE: Record<string, WeekStage> = {
  collecting: 'collect',
  shortlist_review: 'collect',
  slot_voting: 'vote',
  schedule_review: 'schedule',
  published: 'shows',
  running: 'shows',
  closed: 'shows',
}

function finished(s: ServerScreening): boolean {
  const ends = new Date(s.slot.starts_at).getTime() + s.slot.duration_min * 60_000
  return s.status === 'completed' || ends <= Date.now()
}

function showOf(s: ServerScreening): Show {
  const started = new Date(s.slot.starts_at).getTime() <= Date.now()
  const over = finished(s)
  const state: Show['state'] =
    s.status === 'cancelled' ? 'cancelled' : over ? 'past' : started ? 'live' : 'upcoming'
  let myStatus: MyShowStatus = 'none'
  if (over) myStatus = s.i_attended ? 'attended' : 'missed'
  else if (s.my_state === 'confirmed') myStatus = 'going'
  else if (s.my_state === 'waitlist') myStatus = 'queued'
  return {
    id: s.id,
    // У события без фильма в film лежит заглушка с названием и без id.
    film: s.film.id != null ? shortOf(s.film) : undefined,
    title: s.film.id == null ? s.film.title_ru : undefined,
    note: s.note ?? undefined,
    startsAt: s.slot.starts_at,
    place: s.slot.hall_name,
    capacity: s.capacity,
    going: s.confirmed,
    queueLength: 0,
    queuePosition: s.my_place_in_queue ?? undefined,
    state,
    myStatus,
    english: s.in_english,
    registrationUrl: s.registration_url ?? undefined,
    calendarUrl: state === 'upcoming' ? server.calendarUrl(s.id) : undefined,
    cancelReason: s.cancel_reason ?? undefined,
  }
}

async function ballotOf(weekStart: string): Promise<Ballot | undefined> {
  try {
    const b = await server.getBallot()
    if (b.week_start !== weekStart) return undefined
    return {
      weekStart: b.week_start,
      english: b.in_english,
      films: b.films.map(shortOf),
      evenings: b.slots.map((slot) => ({
        id: slot.id,
        startsAt: slot.starts_at,
        place: slot.hall_name,
        closed: slot.blocked,
      })),
      selectedFilmIds: b.my_film_ids,
      selectedEveningIds: b.my_slot_ids,
      closesAt: '',
    }
  } catch {
    return undefined
  }
}

export async function getSchedule(weekStart?: string): Promise<ScheduleWeek> {
  const s = await server.getSchedule(weekStart)
  // Недели без цикла сервер отдаёт как «collecting». Для прошедшей недели это
  // неправда — она прожита, и полоска этапов должна быть пройдена целиком.
  const weekEnd = new Date(`${s.week_start}T00:00:00Z`).getTime() + 7 * 86_400_000
  const stage = s.round_id === 0 && weekEnd < Date.now() ? 'shows' : (STAGE[s.stage] ?? 'collect')
  return {
    week: {
      start: s.week_start,
      stage,
      hasPrev: s.has_prev,
      hasNext: s.has_next,
      votingWeekStart: s.voting_week ?? undefined,
    },
    ballot: stage === 'vote' ? await ballotOf(s.week_start) : undefined,
    shows: s.screenings.map(showOf),
  }
}

export async function saveBallot(weekStart: string, filmIds: number[], eveningIds: number[]): Promise<Ballot> {
  await server.saveVotes(filmIds)
  await server.saveAvailability(eveningIds)
  const ballot = await ballotOf(weekStart)
  if (!ballot) throw new server.ApiError(409, 'Голосование закрыто')
  return ballot
}

/** «Приду» / отмена записи. Если мест нет — сервер ставит в очередь. */
export async function setAttendance(showId: number, going: boolean): Promise<MyShowStatus> {
  const result = going ? await server.confirmScreening(showId) : await server.declineScreening(showId)
  if (result.state === 'confirmed') return 'going'
  if (result.state === 'waitlist') return 'queued'
  return 'none'
}

export async function checkIn(showId: number, code: string): Promise<void> {
  await server.attendByCode(showId, code)
}

// ---------- опрос после показа ----------

const half = (stars: number | undefined) => (stars != null ? Math.round(stars * 2) : null)
const stars = (halfPoints: number | null) => (halfPoints != null ? halfPoints / 2 : undefined)

export async function getSurvey(showId: number): Promise<Survey> {
  const f = await server.getFeedback(showId)
  if (!f.attended) throw new server.ApiError(403, 'Опрос откроется, когда вас отметят на показе')
  return {
    show: {
      id: f.screening_id,
      film: f.film ? shortOf(f.film) : undefined,
      title: f.title ?? undefined,
      startsAt: f.starts_at ?? new Date().toISOString(),
      place: f.hall_name ?? '',
      capacity: 0,
      going: 0,
      queueLength: 0,
      state: 'past',
      myStatus: 'attended',
    },
    ticketNo: f.screening_id,
    hideFilmQuestion: !f.film || f.film_already_rated,
    answers: {
      overall: stars(f.visit_rating),
      film: stars(f.film_rating),
      discussion: f.discussion_skip ?? stars(f.discussion_rating),
      comment: f.review_text ?? '',
    },
  }
}

export async function submitSurvey(showId: number, answers: SurveyAnswers, filmAlreadyRated = false): Promise<void> {
  const skip = answers.discussion === 'absent' || answers.discussion === 'unsure' ? answers.discussion : null
  await server.saveFeedback(showId, {
    visit_rating: half(answers.overall),
    film_rating: filmAlreadyRated ? null : half(answers.film),
    discussion_rating: typeof answers.discussion === 'number' ? half(answers.discussion) : null,
    discussion_skip: skip,
    review_text: answers.comment.trim() || null,
  })
}

// ---------- профиль ----------

export async function getProfile(userId: number): Promise<Profile> {
  const p: ServerProfile = await server.getProfile(userId)
  const a = p.achievements
  const pending = p.is_me
    ? (await server.myFilmRequests().catch(() => [])).filter((r) => r.status === 'pending').length
    : 0
  return {
    id: p.id,
    name: p.display_name,
    username: p.tg_username ?? undefined,
    avatarUrl: p.photo_url ?? undefined,
    role: p.role,
    isMe: p.is_me,
    relation: { friends: p.relation_friends, following: p.relation_following, follower: p.relation_follower },
    counts: { marks: p.marks, seen: p.watched, friends: p.friends },
    ratingHistogram: p.ratings_by_score,
    ratingAvg: p.average_rating ?? undefined,
    favorites: p.favourites.map(shortOf),
    achievements: {
      bronze: a.bronze,
      silver: a.silver,
      gold: a.gold,
      platinum: a.platinum,
      total: a.bronze + a.silver + a.gold + a.platinum,
    },
    attendance:
      p.attendance.came + p.attendance.planned > 0
        ? {
            attended: p.attendance.came,
            planned: p.attendance.planned,
            missed: Math.max(p.attendance.planned - p.attendance.came, 0),
            percent: Math.round((p.attendance.ratio ?? 0) * 100),
          }
        : undefined,
    pendingRequests: pending,
    raw: p,
  }
}

export async function toggleFriend(userId: number, following: boolean): Promise<void> {
  if (following) await server.removeFriend(userId)
  else await server.addFriend(userId)
}

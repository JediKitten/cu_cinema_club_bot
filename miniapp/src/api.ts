import { getInitData } from "./telegram";
import type {
  Ballot,
  FilmBrief,
  FilmCard,
  FilmRequest,
  InterestKind,
  InterestState,
  Analytics,
  Attendee,
  ConfirmResult,
  FeedbackState,
  Matrix,
  PastScreening,
  Rankings,
  Role,
  Round,
  Setting,
  Schedule,
  ScreeningCode,
  Slot,
  TeamMember,
  User,
} from "./types";

// Пусто по умолчанию: запросы идут на тот же origin, а dev-сервер Vite проксирует
// их на бэкенд. Переопределяется через VITE_API_URL, если API вынесен отдельно.
const BASE = import.meta.env.VITE_API_URL ?? "";

let token: string | null = null;

export class ApiError extends Error {
  // Поле объявлено отдельно от конструктора: параметры-свойства TypeScript
  // запрещены при erasableSyntaxOnly, включённом в шаблоне Vite.
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    // FastAPI кладёт человекочитаемое сообщение в detail — показываем его,
    // а не «500 Internal Server Error».
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* тело не json — оставляем статус */
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export async function login(): Promise<User> {
  const initData = getInitData();
  if (!initData) {
    throw new ApiError(401, "Откройте приложение через Telegram");
  }
  const auth = await request<{ token: string; user: User }>("/api/auth/telegram", {
    method: "POST",
    body: JSON.stringify({ init_data: initData }),
  });
  token = auth.token;
  return auth.user;
}

export const searchFilms = (query: string) =>
  request<FilmBrief[]>(`/api/films/search?q=${encodeURIComponent(query)}`);

export const browseFilms = (sort: string, offset = 0) =>
  request<FilmBrief[]>(`/api/films?sort=${sort}&offset=${offset}`);

export const getFilm = (filmId: number) => request<FilmCard>(`/api/films/${filmId}`);

// Карточка фильма, которого ещё нет в каталоге: данные берутся из TMDB
// и не сохраняются — фильм заводится только при первой отметке.
export const getTmdbFilm = (tmdbId: number) =>
  request<FilmCard>(`/api/films/tmdb/${tmdbId}`);

export const myInterests = () => request<InterestState[]>("/api/me/interests");

/** Фильм из поиска TMDB ещё не в каталоге — тогда отмечаем по tmdb_id,
 *  и бэкенд заводит карточку в этот момент. */
export const addInterest = (film: FilmBrief, kind: InterestKind) =>
  film.id
    ? request<InterestState>(`/api/films/${film.id}/interest`, {
        method: "POST",
        body: JSON.stringify({ kind }),
      })
    : request<InterestState>("/api/interests", {
        method: "POST",
        body: JSON.stringify({ kind, tmdb_id: film.tmdb_id }),
      });

// Вид не передаём: состояние одно, снимать нечего кроме него.
export const removeInterest = (filmId: number) =>
  request<InterestState>(`/api/films/${filmId}/interest`, { method: "DELETE" });

// Фильма из поиска TMDB ещё нет в каталоге — тогда отмечаем по tmdb_id,
// и бэкенд заводит карточку в этот момент.
export const setWatched = (film: FilmBrief, watched: boolean) =>
  film.id
    ? request<InterestState>(`/api/films/${film.id}/watched`, {
        method: "POST",
        body: JSON.stringify({ watched }),
      })
    : request<InterestState>("/api/watched", {
        method: "POST",
        body: JSON.stringify({ watched, tmdb_id: film.tmdb_id }),
      });

export const createFilmRequest = (payload: {
  raw_title: string;
  raw_year: number | null;
  note: string | null;
}) => request<FilmRequest>("/api/film-requests", { method: "POST", body: JSON.stringify(payload) });

export const myFilmRequests = () => request<FilmRequest[]>("/api/me/film-requests");

// --- Админка ---------------------------------------------------------------

export const getRankings = () => request<Rankings>("/api/admin/rankings");

export const getRound = () => request<Round | null>("/api/admin/round");

export const openRound = () =>
  request<Round>("/api/admin/round", { method: "POST", body: JSON.stringify({}) });

export const saveShortlist = (filmIds: number[]) =>
  request<Round>("/api/admin/round/shortlist", {
    method: "PUT",
    body: JSON.stringify({ film_ids: filmIds }),
  });

export const publishShortlist = () =>
  request<Round>("/api/admin/round/shortlist/publish", { method: "POST" });

export const blockSlot = (slotId: number, blocked: boolean, reason?: string) =>
  request<Round>(`/api/admin/round/slots/${slotId}/block`, {
    method: "POST",
    body: JSON.stringify({ blocked, reason: reason ?? null }),
  });

// --- Этап 2: голосование ---------------------------------------------------

export const getBallot = () => request<Ballot>("/api/round/ballot");

export const saveVotes = (filmIds: number[]) =>
  request<Ballot>("/api/round/votes", {
    method: "PUT",
    body: JSON.stringify({ film_ids: filmIds }),
  });

export const saveAvailability = (slotIds: number[]) =>
  request<Ballot>("/api/round/availability", {
    method: "PUT",
    body: JSON.stringify({ slot_ids: slotIds }),
  });

export const getMatrix = () => request<Matrix>("/api/round/matrix");

// --- Этап 3: расписание и подтверждения ------------------------------------

export const getSchedule = (week?: string) =>
  request<Schedule>(week ? `/api/schedule?week=${week}` : "/api/schedule");

export const confirmScreening = (id: number) =>
  request<ConfirmResult>(`/api/schedule/screenings/${id}/confirm`, { method: "POST" });

export const declineScreening = (id: number) =>
  request<ConfirmResult>(`/api/schedule/screenings/${id}/decline`, { method: "POST" });

export const getFreeSlots = () => request<Slot[]>("/api/schedule/free-slots");

export const assignScreening = (filmId: number, slotId: number) =>
  request<Schedule>("/api/schedule/assign", {
    method: "POST",
    body: JSON.stringify({ film_id: filmId, slot_id: slotId }),
  });

export const unassignScreening = (id: number) =>
  request<Schedule>(`/api/schedule/screenings/${id}`, { method: "DELETE" });

export const publishSchedule = () =>
  request<Schedule>("/api/schedule/publish", { method: "POST" });

export const cancelScreening = (id: number, reason: string) =>
  request<Schedule>(`/api/schedule/screenings/${id}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

// --- Этап 4: присутствие и оценки ------------------------------------------

export const attendByCode = (screeningId: number, code: string) =>
  request<FeedbackState>(`/api/screenings/${screeningId}/attend`, {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const getFeedback = (screeningId: number) =>
  request<FeedbackState>(`/api/screenings/${screeningId}/feedback`);

export const saveFeedback = (
  screeningId: number,
  payload: { film_rating: number | null; review_text: string | null },
) =>
  request<FeedbackState>(`/api/screenings/${screeningId}/feedback`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });

export const getScreeningCode = (screeningId: number) =>
  request<ScreeningCode>(`/api/screenings/${screeningId}/code`);

export const getAttendees = (screeningId: number) =>
  request<Attendee[]>(`/api/screenings/${screeningId}/attendees`);

// --- Аналитика -------------------------------------------------------------

export const getAnalytics = () => request<Analytics>("/api/admin/analytics");

export const getPastScreenings = () => request<PastScreening[]>("/api/screenings/past");

// --- Управление клубом ------------------------------------------------------

export const getSettings = () => request<Setting[]>("/api/admin/settings");

export const saveSettings = (values: Record<string, unknown>) =>
  request<Setting[]>("/api/admin/settings", {
    method: "PATCH",
    body: JSON.stringify({ values }),
  });

export const getTeam = () => request<TeamMember[]>("/api/admin/team");

export const findUsers = (query: string) =>
  request<TeamMember[]>(`/api/admin/users?q=${encodeURIComponent(query)}`);

export const setUserRole = (userId: number, role: Role) =>
  request<TeamMember>(`/api/admin/users/${userId}/role`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  });

export const getGrantableRoles = () => request<Role[]>("/api/admin/roles");

export const createEvent = (payload: {
  starts_at: string;
  film_id: number | null;
  title: string | null;
  note: string | null;
}) => request<{ id: number }>("/api/admin/events", { method: "POST", body: JSON.stringify(payload) });

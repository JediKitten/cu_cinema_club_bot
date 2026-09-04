import { getInitData } from "./telegram";
import type { FilmBrief, FilmCard, FilmRequest, InterestKind, InterestState, User } from "./types";

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

export const removeInterest = (filmId: number, kind: InterestKind) =>
  request<InterestState>(`/api/films/${filmId}/interest?kind=${kind}`, { method: "DELETE" });

export const createFilmRequest = (payload: {
  raw_title: string;
  raw_year: number | null;
  note: string | null;
}) => request<FilmRequest>("/api/film-requests", { method: "POST", body: JSON.stringify(payload) });

export const myFilmRequests = () => request<FilmRequest[]>("/api/me/film-requests");

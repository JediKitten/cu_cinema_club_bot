import { createContext, useContext } from "react";
import type { FilmBrief } from "./types";

/** Открытие карточки фильма из любого экрана.
 *
 * Через контекст, а не пропсами: карточки показываются в каталоге, «Моих»,
 * расписании, голосовании, истории и админке — протаскивать обработчик через
 * все эти уровни значило бы менять сигнатуры половины компонентов ради одного
 * действия.
 */
const FilmOpener = createContext<((film: FilmBrief) => void) | null>(null);

export const FilmOpenerProvider = FilmOpener.Provider;

export function useOpenFilm(): (film: FilmBrief) => void {
  return useContext(FilmOpener) ?? (() => {});
}

/** Карточка по одному лишь id — для мест, где на руках нет полного объекта. */
export function useOpenFilmById(): (filmId: number, title?: string) => void {
  const open = useOpenFilm();
  return (filmId, title = "") =>
    open({
      id: filmId,
      tmdb_id: null,
      title_ru: title,
      title_orig: null,
      year: null,
      poster_url: null,
      genres: [],
      directors: [],
      in_catalog: true,
      my_interests: [],
      can_renew_soon: false,
      soon_expires_at: null,
      watched: false,
    });
}

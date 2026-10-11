import type { FilmBrief } from "./types";

/** Один ли это фильм.
 *
 * Оба идентификатора необязательны, и сравнивать их «в лоб» нельзя: у фильмов,
 * завезённых из Кинопоиска, `tmdb_id` пуст у всех сразу, и `null === null`
 * делает совпадением любую пару. Именно так весь каталог превращался в копии
 * одного фильма после отметки.
 */
export function isSameFilm(a: FilmBrief, b: FilmBrief): boolean {
  if (a.id != null && b.id != null) return a.id === b.id;
  if (a.tmdb_id != null && b.tmdb_id != null) return a.tmdb_id === b.tmdb_id;
  // Одного не хватает — считаем разными: ложное совпадение portит список,
  // а пропущенное лишь оставит строку неперерисованной до обновления.
  return false;
}

/** Заменяет в списке карточку того же фильма, остальные оставляет как есть. */
export function replaceFilm<T>(
  items: T[],
  updated: FilmBrief,
  filmOf: (item: T) => FilmBrief,
  merge: (item: T) => T,
): T[] {
  return items.map((item) => (isSameFilm(filmOf(item), updated) ? merge(item) : item));
}

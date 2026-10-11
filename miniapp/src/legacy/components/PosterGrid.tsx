import { Poster } from "./FilmRow";
import type { FilmBrief } from "../types";

type Props = {
  films: FilmBrief[];
  onOpen(film: FilmBrief): void;
};

/** Сетка постеров, четыре в ряд.
 *
 * Списком видно подробности, плиткой — весь список сразу: до сотого фильма
 * прокручивать вчетверо меньше. Отметки при этом живут в карточке, поэтому
 * плитка — только постер и нажатие.
 */
export function PosterGrid({ films, onOpen }: Props) {
  return (
    <div className="poster-grid">
      {films.map((film) => (
        <button
          className="poster-grid__item"
          key={film.id ?? `tmdb-${film.tmdb_id}`}
          onClick={() => onOpen(film)}
          title={film.title_ru}
          aria-label={film.title_ru}
        >
          <Poster url={film.poster_url} className="poster--tile" />
          {/* Без постера плитка была бы безымянным прямоугольником. */}
          {!film.poster_url && <span className="poster-grid__title">{film.title_ru}</span>}
        </button>
      ))}
    </div>
  );
}

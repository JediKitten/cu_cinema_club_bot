import { MarkButtons } from "./MarkButtons";
import type { FilmBrief, InterestKind } from "../types";

type Props = {
  film: FilmBrief;
  onOpen(film: FilmBrief): void;
  onMarksChange(kinds: InterestKind[], film: FilmBrief): void;
};

export function Poster({ url, className = "" }: { url: string | null; className?: string }) {
  return url ? (
    <img className={`poster ${className}`} src={url} alt="" loading="lazy" />
  ) : (
    <div className={`poster poster--empty ${className}`}>🎬</div>
  );
}

export function FilmRow({ film, onOpen, onMarksChange }: Props) {
  const subtitle = [film.year, film.title_orig].filter(Boolean).join(" · ");

  return (
    <div className="film-row">
      <Poster url={film.poster_url} />
      <div>
        {/* Карточка открывается только у фильмов из каталога: у найденного в TMDB
            ещё нет id, он появится после первой отметки. */}
        <button
          className="film-row__title"
          style={{ padding: 0, textAlign: "left" }}
          disabled={!film.id}
          onClick={() => film.id && onOpen(film)}
        >
          {film.title_ru}
        </button>
        {subtitle && <p className="meta">{subtitle}</p>}
        {film.directors.length > 0 && (
          // В списке режиссёров может быть трое (братья Руссо и подобные) —
          // показываем двоих, иначе строка ломает вёрстку на узком экране.
          <p className="meta">
            {film.directors.slice(0, 2).join(", ")}
            {film.directors.length > 2 && " и др."}
          </p>
        )}
        {!film.in_catalog && <p className="meta">Найдено в TMDB</p>}
        <MarkButtons film={film} kinds={film.my_interests} onChange={onMarksChange} />
      </div>
    </div>
  );
}

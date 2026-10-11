import { MarkButtons } from "./MarkButtons";
import { WatchedButton } from "./WatchedButton";
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
  // Открываются и фильмы из TMDB: карточка соберётся из их данных, в каталог
  // фильм при этом не попадёт.
  const openable = film.id !== null || film.tmdb_id !== null;

  return (
    // Кликается вся карточка, а не только название: попасть по одной строке
    // текста на телефоне трудно. Кнопки внутри гасят всплытие сами.
    <div
      className={`film-row film-row--watchable ${openable ? "film-row--clickable" : ""}`}
      role={openable ? "button" : undefined}
      tabIndex={openable ? 0 : undefined}
      onClick={() => openable && onOpen(film)}
      onKeyDown={(event) => {
        if (openable && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onOpen(film);
        }
      }}
    >
      <WatchedButton film={film} onChange={onMarksChange} />
      <Poster url={film.poster_url} />
      <div>
        <p className="film-row__title">{film.title_ru}</p>
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

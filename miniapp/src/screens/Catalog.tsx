import { useEffect, useRef, useState } from "react";
import { browseFilms, searchFilms } from "../api";
import { FilmRow } from "../components/FilmRow";
import type { FilmBrief, InterestKind } from "../types";
import { replaceFilm } from "../films";

type Props = { onOpen(film: FilmBrief): void };

type Sort = "popular" | "alphabetical" | "year";

// Популярность первой и по умолчанию — по решению клуба. §11 просил обратного:
// такая сортировка усиливает эффект присоединения к большинству и прячет хвост
// каталога. Компромисс: остальные порядки рядом, в один тап.
const SORTS: { key: Sort; label: string }[] = [
  { key: "popular", label: "По популярности" },
  { key: "alphabetical", label: "По алфавиту" },
  { key: "year", label: "По году" },
];

export function Catalog({ onOpen }: Props) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("popular");
  const [films, setFilms] = useState<FilmBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    const trimmed = query.trim();
    setLoading(true);

    // Пауза перед запросом: поиск ходит в TMDB, дёргать его на каждую букву дорого.
    const timer = setTimeout(async () => {
      try {
        const result = trimmed.length >= 2 ? await searchFilms(trimmed) : await browseFilms(sort);
        // Ответ на устаревший запрос игнорируем, иначе медленный ранний ответ
        // перезапишет свежий.
        if (id === requestId.current) {
          setFilms(result);
          setError(null);
        }
      } catch (e) {
        if (id === requestId.current) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    }, trimmed ? 350 : 0);

    return () => clearTimeout(timer);
  }, [query, sort]);

  function handleMarks(kinds: InterestKind[], updated: FilmBrief) {
    setFilms((current) =>
      replaceFilm(
        current,
        updated,
        (film) => film,
        (film) => ({ ...film, ...updated, my_interests: kinds }),
      ),
    );
  }

  return (
    <div className="screen">
      <div className="search">
        <span>🔍</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Найти фильм"
          autoComplete="off"
        />
        {query && <button onClick={() => setQuery("")}>✕</button>}
      </div>

      {!query.trim() && (
        <div className="marks">
          {SORTS.map((option) => (
            <button
              key={option.key}
              className={`mark ${sort === option.key ? "is-on mark--wishlist" : ""}`}
              onClick={() => setSort(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {loading && <div className="center">Загрузка…</div>}

      {!loading && films.length === 0 && (
        <div className="center">
          {query.trim()
            ? "Ничего не нашлось. Если фильма нет и в TMDB — оставьте заявку во вкладке «Ещё»."
            : "Каталог пока пуст. Найдите первый фильм через поиск."}
        </div>
      )}

      {films.map((film) => (
        <FilmRow
          key={film.id ?? `tmdb-${film.tmdb_id}`}
          film={film}
          onOpen={onOpen}
          onMarksChange={handleMarks}
        />
      ))}
    </div>
  );
}

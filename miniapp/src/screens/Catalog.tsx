import { useEffect, useRef, useState } from "react";
import { browseFilms, CATALOG_PAGE, searchFilms } from "../api";
import { FilmRow } from "../components/FilmRow";
import { TournamentBanner } from "../components/TournamentBanner";
import { PosterGrid } from "../components/PosterGrid";
import {
  LayoutSwitch,
  rememberedLayout,
  rememberLayout,
  type Layout,
} from "../components/LayoutSwitch";
import type { FilmBrief, InterestKind } from "../types";
import { replaceFilm } from "../films";
import { useFilmChanges } from "../filmChanges";

type Props = { onOpen(film: FilmBrief): void; onOpenTournament(id: number): void };

type Sort = "kp" | "tmdb" | "club" | "wanted" | "year";

// Первым — курируемый топ Кинопоиска. Голоса толпы (сортировка по числу
// оценок) усиливали эффект присоединения к большинству, о чём и предупреждал
// §11; список, который не зависит от того, кто что отметил, честнее.
const SORTS: { key: Sort; label: string }[] = [
  { key: "kp", label: "Топ Кинопоиска" },
  { key: "tmdb", label: "По оценкам TMDB" },
  { key: "club", label: "По оценкам клуба" },
  { key: "wanted", label: "Хотят в клубе" },
  { key: "year", label: "По году" },
];

export function Catalog({ onOpen, onOpenTournament }: Props) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("kp");
  const [layout, setLayout] = useState<Layout>(rememberedLayout);
  const [films, setFilms] = useState<FilmBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  // Пришла ли последняя страница целиком: если да, дальше есть что грузить.
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    const trimmed = query.trim();
    setLoading(true);

    // Пауза перед запросом: поиск ходит в TMDB, дёргать его на каждую букву дорого.
    const timer = setTimeout(async () => {
      try {
        const searching = trimmed.length >= 2;
        const result = searching ? await searchFilms(trimmed) : await browseFilms(sort);
        // Ответ на устаревший запрос игнорируем, иначе медленный ранний ответ
        // перезапишет свежий.
        if (id === requestId.current) {
          setFilms(result);
          // У поиска своя выдача и своя граница — подгружать там нечего.
          setHasMore(!searching && result.length === CATALOG_PAGE);
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

  async function loadMore() {
    if (loadingMore) return;
    const id = requestId.current;
    setLoadingMore(true);
    try {
      const next = await browseFilms(sort, films.length);
      // Пока грузили, могли переключить сортировку — тогда ответ уже не к месту.
      if (id === requestId.current) {
        setFilms((current) => [...current, ...next]);
        setHasMore(next.length === CATALOG_PAGE);
      }
    } catch (e) {
      if (id === requestId.current) setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoadingMore(false);
    }
  }

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

  // Отметку могли поменять в карточке поверх списка: правим ту же строку,
  // не перезагружая выдачу — иначе потерялись бы подгруженные страницы.
  useFilmChanges(handleMarks);

  return (
    <div className="screen">
      <TournamentBanner onOpen={onOpenTournament} />

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
        <div className="sorts">
          {/* Порядок выбирают редко и всегда один — трём кнопкам незачем
              занимать строку целиком, тем более рядом с переключателем вида. */}
          <select
            className="field sorts__select"
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
            aria-label="Сортировка"
          >
            {SORTS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
          <LayoutSwitch
            layout={layout}
            onChange={(next) => {
              setLayout(next);
              rememberLayout(next);
            }}
          />
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

      {layout === "grid" ? (
        <PosterGrid films={films} onOpen={onOpen} />
      ) : (
        films.map((film) => (
          <FilmRow
            key={film.id ?? `tmdb-${film.tmdb_id}`}
            film={film}
            onOpen={onOpen}
            onMarksChange={handleMarks}
          />
        ))
      )}

      {hasMore && (
        <button className="primary" disabled={loadingMore} onClick={loadMore}>
          {loadingMore ? "Загружаем…" : "Показать ещё"}
        </button>
      )}
    </div>
  );
}

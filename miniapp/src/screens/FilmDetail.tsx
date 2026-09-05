import { useEffect, useState } from "react";
import { getFilm } from "../api";
import { Poster } from "../components/FilmRow";
import { MarkButtons } from "../components/MarkButtons";
import { WatchedButton } from "../components/WatchedButton";
import { useTelegramBackButton } from "../telegram";
import type { FilmBrief, FilmCard, InterestKind } from "../types";

type Props = { filmId: number; onBack(): void };

function runtime(minutes: number | null): string | null {
  if (!minutes) return null;
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} ч ${minutes % 60} мин` : `${minutes} мин`;
}

export function FilmDetail({ filmId, onBack }: Props) {
  const [film, setFilm] = useState<FilmCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => useTelegramBackButton(true, onBack), [onBack]);

  useEffect(() => {
    getFilm(filmId)
      .then(setFilm)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось открыть карточку"));
  }, [filmId]);

  if (error) return <div className="screen"><div className="error">{error}</div></div>;
  if (!film) return <div className="center">Загрузка…</div>;

  const facts = [film.year, runtime(film.runtime_min), film.genres.join(", ")]
    .filter(Boolean)
    .join(" · ");

  function updateMarks(kinds: InterestKind[], updated: FilmBrief) {
    // Берём всё, что вернул сервер: вместе с отметкой меняются «Просмотрено»
    // и признак истёкшего срока — обновляя только kinds, мы бы их потеряли.
    setFilm((current) => (current ? { ...current, ...updated, my_interests: kinds } : current));
  }

  return (
    <div className="screen detail">
      <div className="detail__head film-row--watchable">
        <WatchedButton film={film} onChange={updateMarks} />
        <Poster url={film.poster_url} />
        <div>
          <h1>{film.title_ru}</h1>
          {film.title_orig && film.title_orig !== film.title_ru && (
            <p className="meta">{film.title_orig}</p>
          )}
          {facts && <p className="meta">{facts}</p>}
          {film.directors.length > 0 && (
            <p className="meta">
              {film.directors.length > 1 ? "Режиссёры" : "Режиссёр"}:{" "}
              {film.directors.join(", ")}
            </p>
          )}
          {film.watched && <p className="badge" style={{ marginTop: 8 }}>Просмотрено</p>}
        </div>
      </div>

      <MarkButtons film={film} kinds={film.my_interests} onChange={updateMarks} full />

      {/* Три числа принципиально разные — не смешиваем их в одну «оценку» (§11). */}
      <div className="ratings">
        <div className="rating">
          <b>{film.interested_count}</b>
          <span>хотят посмотреть</span>
        </div>
        {film.internal_rating !== null && (
          <div className="rating">
            <b>{film.internal_rating}</b>
            <span>клуб · {film.internal_votes} оценок</span>
          </div>
        )}
        {film.ext_rating !== null && (
          <div className="rating">
            <b>{film.ext_rating.toFixed(1)}</b>
            <span>TMDB · {film.ext_votes ?? 0}</span>
          </div>
        )}
      </div>

      {film.internal_rating === null && film.internal_votes > 0 && (
        <p className="hint">
          Оценок клуба пока слишком мало ({film.internal_votes}), рейтинг не показываем.
        </p>
      )}

      {film.trailer_key && (
        <a
          className="link"
          href={`https://www.youtube.com/watch?v=${film.trailer_key}`}
          target="_blank"
          rel="noreferrer"
        >
          ▶ Смотреть трейлер
        </a>
      )}

      {film.overview && <p className="overview">{film.overview}</p>}

      {film.reviews.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, margin: "8px 0 0" }}>Отзывы</h2>
          {film.reviews.map((review, index) => (
            <div className="review" key={index}>
              <div className="review__head">
                <span>{review.author}</span>
                {review.rating !== null && <span>{review.rating}/10</span>}
              </div>
              {review.text}
            </div>
          ))}
        </>
      )}

      <p className="attribution">
        Данные о фильме — TMDB. This product uses the TMDB API but is not endorsed or certified
        by TMDB.
      </p>
    </div>
  );
}

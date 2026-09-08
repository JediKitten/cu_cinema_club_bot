import { useEffect, useState } from "react";
import { ApiError, getFilm, getTmdbFilm, rateFilm } from "../api";
import { Poster } from "../components/FilmRow";
import { MarkButtons } from "../components/MarkButtons";
import { InviteButton } from "../components/InviteButton";
import { WatchedButton } from "../components/WatchedButton";
import { StarRating } from "../components/StarRating";
import { FilmStatsPanel } from "../components/FilmStatsPanel";
import { Section } from "../components/Section";
import { haptic, showMessage, useTelegramBackButton } from "../telegram";
import { plural } from "../plural";
import { publishFilmChange } from "../filmChanges";
import type { FilmBrief, FilmCard, InterestKind } from "../types";

type Props = {
  filmId: number | null;
  tmdbId?: number | null;
  /** Админская статистика по фильму — только тем, кто отбирает шорт-лист. */
  withStats?: boolean;
  onBack(): void;
};

function runtime(minutes: number | null): string | null {
  if (!minutes) return null;
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} ч ${minutes % 60} мин` : `${minutes} мин`;
}

export function FilmDetail({ filmId, tmdbId, withStats = false, onBack }: Props) {
  const [film, setFilm] = useState<FilmCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rating, setRating] = useState(false);

  useEffect(() => useTelegramBackButton(true, onBack), [onBack]);

  useEffect(() => {
    // Фильм из каталога открываем по его id, найденный в поиске — по tmdb_id:
    // во втором случае карточка собирается из TMDB и в базу не пишется.
    const load = filmId !== null ? getFilm(filmId) : getTmdbFilm(tmdbId!);
    load
      .then(setFilm)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, [filmId, tmdbId]);

  if (error) return <div className="screen"><div className="error">{error}</div></div>;
  if (!film) return <div className="center">Загрузка…</div>;

  const facts = [film.year, runtime(film.runtime_min), film.genres.join(", ")]
    .filter(Boolean)
    .join(" · ");

  /** Оценка ставится сразу: подтверждать нечего, а повторное нажатие снимает. */
  async function rate(stars: number | null) {
    if (!film?.id || rating) return;
    setRating(true);
    try {
      const result = await rateFilm(film.id, stars);
      setFilm((current) =>
        current
          ? {
              ...current,
              my_rating: result.my_rating,
              internal_rating: result.internal_rating,
              internal_votes: result.internal_votes,
            }
          : current,
      );
      haptic();
    } catch (e) {
      showMessage(e instanceof ApiError ? e.message : "Не удалось сохранить оценку");
    } finally {
      setRating(false);
    }
  }

  function updateMarks(kinds: InterestKind[], updated: FilmBrief) {
    // Берём всё, что вернул сервер: вместе с отметкой меняются «Просмотрено»
    // и признак истёкшего срока — обновляя только kinds, мы бы их потеряли.
    setFilm((current) => (current ? { ...current, ...updated, my_interests: kinds } : current));
    // Списки под карточкой правят у себя ту же строку, не перезагружаясь.
    publishFilmChange(kinds, updated);
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

      {film.invited_by && (
        // Приглашение по ссылке. Голос не поставлен — человек решает сам.
        <div className="notice" style={{ cursor: "default" }}>
          {film.invited_by} зовёт вас на этот фильм. Решать вам — отметьте, если пойдёте.
        </div>
      )}

      <MarkButtons film={film} kinds={film.my_interests} onChange={updateMarks} full />

      <div className="marks">
        <InviteButton film={film} />
      </div>

      {/* Три числа принципиально разные — не смешиваем их в одну «оценку» (§11).
          Рейтинг клуба стоит отдельно и по своей шкале: пять звёзд, а не десять
          баллов внешнего рейтинга. */}
      <div className="ratings">
        <div className="rating">
          <b>{film.interested_count}</b>
          <span>хотят посмотреть</span>
        </div>
        <div className="rating rating--club">
          <b>{film.internal_rating !== null ? `${film.internal_rating.toFixed(1)} ★` : "—"}</b>
          <span>
            клуб · {film.internal_votes}{" "}
            {plural(film.internal_votes, ["оценка", "оценки", "оценок"])}
          </span>
        </div>
        {/* Оценки источников по отдельности: раньше рейтинг Кинопоиска
            показывался с подписью TMDB — каталог наполняется из обоих. */}
        {film.kp_rating !== null && (
          <div className="rating">
            <b>{film.kp_rating.toFixed(1)}</b>
            <span>Кинопоиск · {film.kp_votes ?? 0}</span>
          </div>
        )}
        {film.tmdb_rating !== null && (
          <div className="rating">
            <b>{film.tmdb_rating.toFixed(1)}</b>
            <span>TMDB · {film.tmdb_votes ?? 0}</span>
          </div>
        )}
      </div>

      {film.id !== null && (
        <div className="rate">
          <p className="hint" style={{ margin: 0 }}>
            {film.my_rating !== null ? "Ваша оценка" : "Оцените фильм"}
          </p>
          <StarRating value={film.my_rating} busy={rating} onChange={rate} />
        </div>
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

      {withStats && film.id !== null && (
        <Section title="Статистика клуба" storageKey="film-stats" defaultOpen={false}>
          <FilmStatsPanel filmId={film.id} />
        </Section>
      )}

      {film.reviews.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, margin: "8px 0 0" }}>Отзывы</h2>
          {film.reviews.map((review, index) => (
            <div className="review" key={index}>
              <div className="review__head">
                <span>{review.author}</span>
                {/* Отзывы писали по десятибалльной форме после показа — на
                    экране всё в одной шкале, звёздной. */}
                {review.rating !== null && <span>{(review.rating / 2).toFixed(1)} ★</span>}
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

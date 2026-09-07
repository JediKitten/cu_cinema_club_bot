import { useEffect, useRef, useState } from "react";
import { addInterest, getDeck, rateFilm, setWatched, skipFilm } from "../api";
import { StarRating } from "../components/StarRating";
import { useFilmChanges } from "../filmChanges";
import { haptic, showMessage } from "../telegram";
import type { DeckCard, FilmBrief } from "../types";

/** Насколько далеко нужно утащить карточку, чтобы это считалось свайпом.
 *  Меньше — и лента срабатывала бы от случайного движения при прокрутке. */
const THRESHOLD = 90;

/** Когда в очереди осталось столько карточек, просим следующую пачку —
 *  дозагрузка должна случиться до того, как экран опустеет. */
const REFILL_AT = 5;

type Decision = "like" | "skip" | "watched";

/** Карточка как объект отметки: у ленты свой формат, а API отметок ждёт фильм. */
function asFilm(card: DeckCard): FilmBrief {
  return {
    id: card.id,
    tmdb_id: null,
    title_ru: card.title_ru,
    title_orig: card.title_orig,
    year: card.year,
    poster_url: card.poster_url,
    genres: card.genres,
    directors: card.directors,
    in_catalog: true,
    my_interests: [],
    can_renew_soon: false,
    soon_expires_at: null,
    watched: false,
  };
}

function runtime(minutes: number | null): string | null {
  if (!minutes) return null;
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} ч ${minutes % 60} мин` : `${minutes} мин`;
}

/** Лента: карточка на весь экран, свайп решает судьбу фильма.
 *
 * Смысл в скорости. Отмечать сотню фильмов списком никто не станет, а
 * пролистать полсотни карточек — минута, и шорт-лист недели после этого
 * собирается из живого интереса, а не из десяти отметок самых упорных.
 */
export function Deck({ onOpen }: { onOpen(film: FilmBrief): void }) {
  const [queue, setQueue] = useState<DeckCard[]>([]);
  const [left, setLeft] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Смещение карточки под пальцем и направление, в которое она улетает.
  const [drag, setDrag] = useState(0);
  const [flying, setFlying] = useState<Decision | null>(null);
  const start = useRef<number | null>(null);
  const loadingMore = useRef(false);

  const card = queue[0] ?? null;

  async function refill(holding: DeckCard[]) {
    if (loadingMore.current) return;
    loadingMore.current = true;
    try {
      const next = await getDeck(holding.map((item) => item.id));
      setQueue((current) => {
        // Пока грузили, часть карточек могли уже пролистать: склеиваем по id,
        // иначе в очередь вернулось бы то, что уже улетело.
        const known = new Set(current.map((item) => item.id));
        return [...current, ...next.cards.filter((item) => !known.has(item.id))];
      });
      setLeft(next.left);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить ленту");
    } finally {
      loadingMore.current = false;
      setLoading(false);
    }
  }

  useEffect(() => {
    refill([]);
    // Первая загрузка: дальше пополняем по мере расхода очереди.
  }, []);

  useEffect(() => {
    if (!loading && queue.length <= REFILL_AT && (left === null || left > queue.length)) {
      refill(queue);
    }
  }, [queue, loading, left]);

  // Карточку могли отметить в подробном виде поверх ленты — тогда решать
  // по ней уже нечего, и она уходит из очереди.
  useFilmChanges((kinds, film) => {
    if (kinds.length > 0 || film.watched) {
      setQueue((current) => current.filter((item) => item.id !== film.id));
    }
  });

  async function decide(decision: Decision, stars: number | null = null) {
    if (!card || busy) return;
    setBusy(true);
    setFlying(decision);
    haptic(decision === "skip" ? "light" : "medium");

    try {
      if (decision === "like") await addInterest(asFilm(card), "wishlist");
      else if (decision === "watched") {
        // Оценка сама по себе значит «смотрел»: спрашивать об этом отдельно
        // после того, как человек поставил звёзды, было бы издевательством.
        if (stars !== null) await rateFilm(card.id, stars);
        await setWatched(asFilm(card), true);
      } else await skipFilm(card.id);

      setQueue((current) => current.slice(1));
      setLeft((value) => (value === null ? null : Math.max(0, value - 1)));
    } catch (e) {
      showMessage(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setFlying(null);
      setDrag(0);
      setBusy(false);
    }
  }

  function onPointerDown(event: React.PointerEvent) {
    if (busy) return;
    start.current = event.clientX;
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: React.PointerEvent) {
    if (start.current === null) return;
    setDrag(event.clientX - start.current);
  }

  function onPointerUp() {
    if (start.current === null) return;
    const shift = drag;
    start.current = null;
    if (shift > THRESHOLD) void decide("like");
    else if (shift < -THRESHOLD) void decide("skip");
    else setDrag(0);
  }

  if (loading) return <div className="center">Собираем ленту…</div>;
  if (error && !card) return <div className="screen"><div className="error">{error}</div></div>;

  if (!card) {
    return (
      <div className="center">
        Лента кончилась — вы разметили весь каталог.
        <br />
        Новые фильмы появятся здесь, как только их добавят.
      </div>
    );
  }

  // Улетающая карточка уходит за край экрана, «живая» — следует за пальцем.
  const offset = flying === "like" ? 500 : flying === "skip" ? -500 : drag;
  const hint = drag > THRESHOLD ? "like" : drag < -THRESHOLD ? "skip" : null;

  return (
    <div className="deck">
      <div
        className="deck__card"
        style={{
          transform: `translateX(${offset}px) rotate(${offset / 22}deg)`,
          transition: flying || drag === 0 ? "transform 0.25s ease-out" : "none",
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {card.poster_url ? (
          <img className="deck__poster" src={card.poster_url} alt="" draggable={false} />
        ) : (
          <div className="deck__poster deck__poster--empty">🎬</div>
        )}

        {/* Счётчик поверх постера, а не строкой внизу: вертикаль на этом
            экране дороже всего, а знать, сколько осталось, полезно. */}
        {left !== null && left > 0 && <div className="deck__counter">осталось {left}</div>}

        {/* Подсказка о решении появляется до того, как палец отпущен. */}
        {hint && <div className={`deck__stamp deck__stamp--${hint}`}>
          {hint === "like" ? "Хочу посмотреть" : "Не моё"}
        </div>}

        <div className="deck__body">
          <h2 className="deck__title">{card.title_ru}</h2>
          <p className="meta">
            {[card.year, runtime(card.runtime_min), card.genres.slice(0, 2).join(", ")]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <div className="deck__ratings">
            {card.internal_rating !== null && (
              <span className="badge deck__badge--club">
                клуб {card.internal_rating.toFixed(1)} ★ · {card.internal_votes}
              </span>
            )}
            {card.ext_rating !== null && (
              <span className="badge">TMDB {card.ext_rating.toFixed(1)}</span>
            )}
          </div>
          {card.overview && <p className="deck__overview">{card.overview}</p>}
          <button className="mark" onClick={() => onOpen(asFilm(card))}>
            Подробнее
          </button>
        </div>
      </div>

      {/* Кнопки — не украшение: свайп на десктопе неудобен, а «уже смотрел»
          третьим направлением быть не может. */}
      <div className="deck__actions">
        <button className="deck__action" disabled={busy} onClick={() => decide("skip")}>
          ✕<span>не моё</span>
        </button>
        <button
          className="deck__action deck__action--watched"
          disabled={busy}
          onClick={() => decide("watched")}
        >
          👁<span>уже смотрел</span>
        </button>
        <button
          className="deck__action deck__action--like"
          disabled={busy}
          onClick={() => decide("like")}
        >
          ♥<span>хочу</span>
        </button>
      </div>

      {/* Смотревшему есть что сказать точнее, чем «смотрел»: оценка тут же
          и засчитывает просмотр, и попадает в рейтинг клуба. */}
      <div className="deck__rate">
        <span className="hint">Смотрели? Оцените:</span>
        <StarRating value={null} busy={busy} onChange={(stars) => decide("watched", stars)} />
      </div>

    </div>
  );
}

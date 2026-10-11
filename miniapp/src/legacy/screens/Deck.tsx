import { useEffect, useRef, useState } from "react";
import { addInterest, getDeck, rateFilm, setWatched, skipFilm } from "../api";
import { StarRating } from "../components/StarRating";
import { useFilmChanges } from "../filmChanges";
import { askConfirm, haptic, showMessage } from "../telegram";
import type { DeckCard, FilmBrief } from "../types";

/** Насколько далеко нужно утащить карточку, чтобы это считалось свайпом.
 *  Меньше — и лента срабатывала бы от случайного движения при прокрутке. */
const THRESHOLD = 90;

/** Когда в очереди осталось столько карточек, просим следующую пачку —
 *  дозагрузка должна случиться до того, как экран опустеет. Быстрый свайп
 *  съедает пять карточек за десяток секунд, так что запас нужен заметный. */
const REFILL_AT = 8;

const LOSES_RATING =
  "Оценка не сохранится: чтобы она осталась, нажмите «Смотрел». Продолжить?";

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
  // Оценка, выставленная на этой карточке и ещё не сохранённая: сохраняет её
  // только «Смотрел» — звёзды сами по себе не решают судьбу фильма.
  const [stars, setStars] = useState<number | null>(null);
  // «Смотрел» нажали, а оценки нет: подсвечиваем звёзды и ждём второго нажатия.
  const [asking, setAsking] = useState(false);
  // Смещение карточки под пальцем и направление, в которое она улетает.
  const [drag, setDrag] = useState(0);
  const [flying, setFlying] = useState<Decision | null>(null);
  const start = useRef<number | null>(null);
  // Смещение дублируется ссылкой: между «палец двинулся» и «палец отпущен»
  // React может не успеть перерисоваться, и обработчик отпускания увидел бы
  // старое состояние — быстрый свайп тогда просто не срабатывал.
  const shift = useRef(0);
  const loadingMore = useRef(false);

  const card = queue[0] ?? null;

  // Лента — единственный экран без прокрутки: под пальцем здесь карточка, и
  // страница, уезжающая вместе с ней, сбивает жест. Замок снимаем при уходе
  // с вкладки, иначе остальные экраны остались бы без прокрутки.
  useEffect(() => {
    document.body.classList.add("is-locked");
    return () => document.body.classList.remove("is-locked");
  }, []);

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

  function advance() {
    setQueue((current) => current.slice(1));
    setLeft((value) => (value === null ? null : Math.max(0, value - 1)));
    setStars(null);
    setAsking(false);
  }

  async function decide(decision: Decision) {
    if (!card || busy) return;

    // Свайп поверх выставленной оценки её потеряет — предупреждаем до того,
    // как карточка улетит, а не после.
    if (decision !== "watched" && stars !== null && !(await askConfirm(LOSES_RATING))) {
      setDrag(0);
      return;
    }

    // «Смотрел» без оценки: сначала показываем, где её ставят. Половина
    // проходит мимо звёзд просто потому, что не заметила их. Второе нажатие
    // проходит дальше — настаивать на оценке мы не вправе.
    if (decision === "watched" && stars === null && !asking) {
      setAsking(true);
      haptic("light");
      return;
    }

    setBusy(true);
    setFlying(decision);
    haptic(decision === "skip" ? "light" : "medium");

    try {
      if (decision === "like") await addInterest(asFilm(card), "wishlist");
      else if (decision === "watched") {
        if (stars !== null) await rateFilm(card.id, stars);
        await setWatched(asFilm(card), true);
      } else await skipFilm(card.id);

      advance();
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
    // Кнопке внутри карточки жест не мешаем: она сама решает, что с ним делать.
    if ((event.target as HTMLElement).closest("button")) return;
    start.current = event.clientX;
    // Захват на самой карточке, а не на том, где оказался палец: иначе жест,
    // начатый на тексте, обрывался, стоило пальцу уйти за пределы абзаца.
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: React.PointerEvent) {
    if (start.current === null) return;
    shift.current = event.clientX - start.current;
    setDrag(shift.current);
  }

  function onPointerUp() {
    if (start.current === null) return;
    const moved = shift.current;
    start.current = null;
    shift.current = 0;
    if (moved > THRESHOLD) void decide("like");
    else if (moved < -THRESHOLD) void decide("skip");
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
      {/* Куда тянуть — написано над карточкой: жест, о котором не сказали,
          не существует. Подсказка подсвечивается по ходу свайпа. */}
      <div className="deck__legend">
        <span className={hint === "skip" ? "is-on" : ""}>← не моё</span>
        <span className="hint">
          {left !== null && left > 0 ? `осталось ${left}` : ""}
        </span>
        <span className={hint === "like" ? "is-on deck__legend--like" : ""}>
          хочу посмотреть →
        </span>
      </div>

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

        {/* Печать поверх карточки: решение видно до того, как палец отпущен. */}
        {hint && (
          <div className={`deck__stamp deck__stamp--${hint}`}>
            {hint === "like" ? "Хочу посмотреть" : "Не моё"}
          </div>
        )}

        <div className="deck__body">
          {/* Почему фильм здесь. Рекомендация без объяснения выглядит
              случайной, а «друг оценил на 5» решает за секунду. */}
          {card.reason && <p className="deck__reason">{card.reason}</p>}
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
            {card.kp_rating !== null && (
              <span className="badge">КП {card.kp_rating.toFixed(1)}</span>
            )}
            {card.tmdb_rating !== null && (
              <span className="badge">TMDB {card.tmdb_rating.toFixed(1)}</span>
            )}
          </div>
          {card.overview && <p className="deck__overview">{card.overview}</p>}
          <button className="mark" onClick={() => onOpen(asFilm(card))}>
            Подробнее
          </button>
        </div>
      </div>

      {/* Внизу только то, чего нельзя показать жестом: оценка и «смотрел».
          Свайпы отвечают за «хочу» и «не моё», дублировать их кнопками незачем. */}
      <div className={`deck__footer ${asking ? "is-asking" : ""}`}>
        <StarRating
          value={stars}
          busy={busy}
          onChange={(value) => {
            setStars(value);
            setAsking(false);
          }}
        />
        <button
          className={`mark mark--soon ${stars !== null ? "is-on" : ""}`}
          disabled={busy}
          onClick={() => decide("watched")}
        >
          Смотрел
        </button>
      </div>
      <p className={`hint deck__note ${asking ? "deck__note--asking" : ""}`}>
        {asking
          ? "Оцените фильм — или нажмите «Смотрел» ещё раз, без оценки."
          : stars !== null
            ? "Нажмите «Смотрел», чтобы сохранить оценку."
            : "Оценка сохранится по кнопке «Смотрел»."}
      </p>
    </div>
  );
}

import { useEffect, useState } from "react";
import { ApiError, getBallot, saveAvailability, saveVotes } from "../api";
import { Poster } from "../components/FilmRow";
import { dayLabel, timeLabel } from "../dates";
import { useOpenFilm } from "../filmOpener";
import { haptic } from "../telegram";
import type { Ballot } from "../types";

const same = (left: number[], right: number[]): boolean =>
  left.length === right.length && left.every((id) => right.includes(id));

/** Незаконченный бюллетень переживает уход с вкладки.
 *
 * Вкладка размонтируется при переключении, и с кнопкой «сохранить» это значило
 * бы, что отмеченные, но не отправленные фильмы просто исчезают. Держим их
 * в модуле, а не в состоянии экрана: цикл в ключе, чтобы черновик прошлой
 * недели не всплыл на следующей.
 */
let draft: { round: number; films: number[]; slots: number[] } | null = null;

/** Этап 2 (§6): два независимых выбора — фильмы и вечера.
 *
 * Бюллетень заполняется целиком и отправляется кнопкой. Раньше каждое нажатие
 * уходило на сервер само: отметить пять фильмов на медленной сети значило пять
 * раз подождать, и всё это время кнопки не нажимались. Теперь выбор мгновенный
 * и локальный, а сеть трогается один раз — и человеку видно, что именно он
 * отправляет.
 */
export function Vote() {
  const [ballot, setBallot] = useState<Ballot | null>(null);
  // Черновик: то, что человек выбрал сейчас. `ballot` хранит сохранённое,
  // и разница между ними — это и есть «есть что сохранять».
  const [films, setFilms] = useState<number[]>([]);
  const [slots, setSlots] = useState<number[]>([]);
  const [closed, setClosed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const openFilm = useOpenFilm();

  useEffect(() => {
    getBallot()
      .then((next) => {
        setBallot(next);
        const kept = draft?.round === next.round_id ? draft : null;
        setFilms(kept ? kept.films : next.my_film_ids);
        setSlots(kept ? kept.slots : next.my_slot_ids);
      })
      .catch((e) => {
        // 409 — голосования сейчас нет; это нормальное состояние, а не сбой.
        if (e instanceof ApiError && e.status === 409) setClosed(e.message);
        else setError(e instanceof Error ? e.message : "Не удалось загрузить");
      });
  }, []);

  // Черновик пишем эффектом, а не в самом обработчике: два быстрых нажатия
  // подряд случаются в одном кадре, и обработчик, считающий новый список
  // из текущего состояния, во второй раз видит ещё старое — первый выбор
  // при этом теряется.
  useEffect(() => {
    if (ballot) draft = { round: ballot.round_id, films, slots };
  }, [ballot, films, slots]);

  function toggle(kind: "film" | "slot", id: number) {
    haptic();
    const flip = (current: number[]) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id];
    if (kind === "film") setFilms(flip);
    else setSlots(flip);
  }

  async function save() {
    if (!ballot || busy) return;
    setBusy(true);
    setError(null);
    try {
      // Уходит только изменённое: два запроса там, где поменяли одно,
      // — лишняя работа и лишний повод для ошибки.
      let saved = ballot;
      if (!same(films, ballot.my_film_ids)) saved = await saveVotes(films);
      if (!same(slots, ballot.my_slot_ids)) saved = await saveAvailability(slots);
      setBallot(saved);
      setFilms(saved.my_film_ids);
      setSlots(saved.my_slot_ids);
      haptic("medium");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  if (closed) {
    return (
      <div className="center">
        <p>{closed}</p>
        <p className="hint">
          Голосование открывается раз в неделю, когда объявлен шорт-лист. Отмечайте
          фильмы в каталоге — из них он и собирается.
        </p>
      </div>
    );
  }

  if (error && !ballot) return <div className="error">{error}</div>;
  if (!ballot) return <div className="center">Загрузка…</div>;

  const noEvenings = films.length > 0 && slots.length === 0;
  const dirty = !same(films, ballot.my_film_ids) || !same(slots, ballot.my_slot_ids);

  return (
    <>
      <p className="hint">Выберите фильмы и вечера — расписание соберём из ответов.</p>

      {error && <div className="error">{error}</div>}

      <h3>На какие фильмы пошли бы</h3>
      <p className="hint">Можно отметить сколько угодно — это не рейтинг.</p>

      {ballot.films.map((film) => {
        const on = film.id !== null && films.includes(film.id);
        return (
          <button
            key={film.id}
            className={`film-row choice ${on ? "is-on" : ""}`}
            onClick={() => film.id && toggle("film", film.id)}
          >
            {/* Строка целиком — это выбор, поэтому карточку открывает постер:
                иначе нажатие означало бы сразу два разных действия. */}
            <span
              role="button"
              tabIndex={0}
              onClick={(event) => {
                event.stopPropagation();
                openFilm(film);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.stopPropagation();
                  openFilm(film);
                }
              }}
            >
              <Poster url={film.poster_url} />
            </span>
            <div>
              <p className="film-row__title">{film.title_ru}</p>
              <p className="meta">
                {[film.year, film.directors.slice(0, 2).join(", ")].filter(Boolean).join(" · ")}
              </p>
            </div>
            <span className="choice__tick">{on ? "✓" : ""}</span>
          </button>
        );
      })}

      <h3>Когда свободны</h3>
      {noEvenings && (
        // §6: голос за фильм без свободного вечера ни на что не влияет.
        <div className="warn">
          Отметьте хотя бы один вечер — иначе ваш голос не попадёт ни в один сеанс.
        </div>
      )}

      {ballot.slots.map((slot) => {
        const on = slots.includes(slot.id);
        return (
          <button
            key={slot.id}
            className={`slot-row choice ${on ? "is-on" : ""}`}
            onClick={() => toggle("slot", slot.id)}
          >
            <div>
              <p className="film-row__title">{dayLabel(slot.starts_at)}</p>
              <p className="meta">
                {timeLabel(slot.starts_at)} · {slot.hall_name}
              </p>
            </div>
            <span className="choice__tick">{on ? "✓" : ""}</span>
          </button>
        );
      })}

      {/* Кнопка липнет к низу: список длинный, и после последнего вечера
          пришлось бы прокручивать обратно наверх. */}
      <div className="sticky-actions">
        <button className="primary" disabled={busy || !dirty} onClick={() => void save()}>
          {dirty ? "Сохранить выбор" : "Сохранено ✓"}
        </button>
      </div>
    </>
  );
}

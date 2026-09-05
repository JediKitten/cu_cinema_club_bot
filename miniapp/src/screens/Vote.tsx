import { useEffect, useState } from "react";
import { ApiError, getBallot, saveAvailability, saveVotes } from "../api";
import { Poster } from "../components/FilmRow";
import { dayLabel, timeLabel } from "../dates";
import { haptic } from "../telegram";
import type { Ballot } from "../types";

/** Этап 2 (§6): два независимых выбора — фильмы и вечера.
 *
 * Сохраняем сразу по нажатию, без кнопки «применить»: выбор — это состояние,
 * и отдельный шаг подтверждения только добавил бы способ его потерять.
 */
export function Vote() {
  const [ballot, setBallot] = useState<Ballot | null>(null);
  const [closed, setClosed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getBallot()
      .then(setBallot)
      .catch((e) => {
        // 409 — голосования сейчас нет; это нормальное состояние, а не сбой.
        if (e instanceof ApiError && e.status === 409) setClosed(e.message);
        else setError(e instanceof Error ? e.message : "Не удалось загрузить");
      });
  }, []);

  async function toggle(kind: "film" | "slot", id: number) {
    if (!ballot || busy) return;
    haptic();
    setBusy(true);

    const current = kind === "film" ? ballot.my_film_ids : ballot.my_slot_ids;
    const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id];

    // Показываем результат сразу, не дожидаясь сервера: иначе на медленной
    // сети кнопка кажется залипшей.
    setBallot({ ...ballot, [kind === "film" ? "my_film_ids" : "my_slot_ids"]: next });

    try {
      const saved = kind === "film" ? await saveVotes(next) : await saveAvailability(next);
      setBallot(saved);
      setError(null);
    } catch (e) {
      setBallot(ballot); // откатываем к тому, что реально сохранено
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

  const noEvenings = ballot.my_film_ids.length > 0 && ballot.my_slot_ids.length === 0;

  return (
    <>
      <p className="hint">Выберите фильмы и вечера — расписание соберём из ответов.</p>

      {error && <div className="error">{error}</div>}

      <h3>На какие фильмы пошли бы</h3>
      <p className="hint">Можно отметить сколько угодно — это не рейтинг.</p>

      {ballot.films.map((film) => {
        const on = film.id !== null && ballot.my_film_ids.includes(film.id);
        return (
          <button
            key={film.id}
            className={`film-row choice ${on ? "is-on" : ""}`}
            onClick={() => film.id && toggle("film", film.id)}
            disabled={busy}
          >
            <Poster url={film.poster_url} />
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
        const on = ballot.my_slot_ids.includes(slot.id);
        return (
          <button
            key={slot.id}
            className={`slot-row choice ${on ? "is-on" : ""}`}
            onClick={() => toggle("slot", slot.id)}
            disabled={busy}
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
    </>
  );
}

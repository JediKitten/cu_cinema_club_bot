import { useEffect, useState } from "react";
import { getAttendees, getScreeningCode } from "../api";
import { timeLabel } from "../dates";
import type { Attendee, Screening, ScreeningCode } from "../types";

/** Проведение сеанса (§8): экран для зала.
 *
 * Показывает код, который зрители вводят у себя, и живой список отметившихся.
 * Код меняется каждую минуту, поэтому перезапрашиваем его по остатку времени,
 * а не по фиксированному интервалу — иначе на экране висел бы протухший.
 */
export function RunScreening({ screening, onBack }: { screening: Screening; onBack(): void }) {
  const [code, setCode] = useState<ScreeningCode | null>(null);
  const [attendees, setAttendees] = useState<Attendee[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;

    async function tick() {
      try {
        const next = await getScreeningCode(screening.id);
        if (!alive) return;
        setCode(next);
        setError(null);
        // Запрашиваем следующий сразу после смены, с секундой запаса.
        timer = window.setTimeout(tick, (next.valid_for + 1) * 1000);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Не удалось получить код");
        timer = window.setTimeout(tick, 5000);
      }
    }

    async function refreshList() {
      try {
        const list = await getAttendees(screening.id);
        if (alive) setAttendees(list);
      } catch {
        /* список не критичен — код важнее */
      }
    }

    void tick();
    void refreshList();
    const listTimer = window.setInterval(refreshList, 5000);

    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
      window.clearInterval(listTimer);
    };
  }, [screening.id]);

  return (
    <div className="screen">
      <button className="mark" style={{ alignSelf: "flex-start" }} onClick={onBack}>
        ← Назад
      </button>

      <div className="round-head">
        <b>{screening.film.title_ru}</b>
        <p className="meta">
          {timeLabel(screening.slot.starts_at)} · {screening.slot.hall_name}
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      {code && !code.window_open && (
        <div className="warn">
          Окно отметки закрыто: код принимается только в первые минуты сеанса.
        </div>
      )}

      {code && (
        <>
          <div className="big-code">{code.code}</div>
          {/* Полоска показывает, сколько код ещё живёт — в зале это понятнее цифры. */}
          <div
            className="code-bar"
            style={{ width: `${(code.valid_for / code.rotates_every) * 100}%` }}
          />
          <p className="hint">
            Покажите код на экране. Он меняется каждые {code.rotates_every} с.
          </p>
        </>
      )}

      <h3>Отметились: {attendees.length}</h3>
      {attendees.length === 0 && <p className="hint">Пока никого.</p>}
      {attendees.map((person) => (
        <div className="slot-row" key={person.user_id}>
          <div>
            <p className="film-row__title">{person.display_name}</p>
            <p className="meta">
              {new Date(person.marked_at).toLocaleTimeString("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
              })}
              {person.method === "manual" && " · добавлен вручную"}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

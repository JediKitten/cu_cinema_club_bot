import { useEffect, useState } from "react";
import {
  ApiError,
  assignScreening,
  cancelScreening,
  getFreeSlots,
  getSchedule,
  publishSchedule,
  unassignScreening,
} from "../api";
import { dayLabel, timeLabel } from "../dates";
import { showMessage } from "../telegram";
import { RunScreening } from "../screens/RunScreening";
import type { FilmBrief, Schedule, Screening, Slot } from "../types";

type Props = { shortlist: FilmBrief[] };

/** Расстановка показов (§7).
 *
 * Матрица рядом отвечает на вопрос «какой вечер лучше», а здесь администратор
 * фиксирует решение. Ограничения (один показ на вечер, один фильм за цикл)
 * держит база, поэтому тут не дублируем проверки — показываем ответ сервера.
 */
export function ScheduleBuilder({ shortlist }: Props) {
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [film, setFilm] = useState<number | "">("");
  const [slot, setSlot] = useState<number | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<Screening | null>(null);

  async function reload() {
    const [next, free] = await Promise.all([getSchedule(), getFreeSlots()]);
    setSchedule(next);
    setSlots(free);
  }

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  async function act(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  if (running) {
    return <RunScreening screening={running} onBack={() => setRunning(null)} />;
  }

  if (error && !schedule) return <div className="error">{error}</div>;
  if (!schedule) return <p className="hint">Загрузка расписания…</p>;

  const placed = schedule.screenings.filter((s) => s.status !== "cancelled");
  const placedFilms = new Set(placed.map((s) => s.film.id));
  const available = shortlist.filter((f) => f.id !== null && !placedFilms.has(f.id));

  return (
    <>
      {error && <div className="error">{error}</div>}

      {placed.map((screening) => (
        <div className="film-row" key={screening.id} style={{ gridTemplateColumns: "1fr auto" }}>
          <div>
            <p className="film-row__title">{screening.film.title_ru}</p>
            <p className="meta">
              {dayLabel(screening.slot.starts_at)} · {timeLabel(screening.slot.starts_at)}
            </p>
            <p className="meta">
              ожидаем {screening.expected_attendance ?? "?"} · подтвердили {screening.confirmed}
            </p>
          </div>
          {schedule.published ? (
            <div className="marks" style={{ marginTop: 0 }}>
            <button className="mark mark--wishlist is-on" onClick={() => setRunning(screening)}>
              Провести
            </button>
            <button
              className="mark"
              disabled={busy}
              onClick={() => {
                // Комментарий обязателен: он уходит всем, кто собирался прийти.
                const reason = prompt("Причина отмены — она уйдёт всем, кто собирался прийти:");
                if (reason && reason.trim().length >= 3) {
                  void act(() => cancelScreening(screening.id, reason.trim()));
                } else if (reason !== null) {
                  showMessage("Причину нужно указать");
                }
              }}
            >
              Отменить
            </button>
            </div>
          ) : (
            <button className="mark" disabled={busy} onClick={() => act(() => unassignScreening(screening.id))}>
              Снять
            </button>
          )}
        </div>
      ))}

      {!schedule.published && (
        <>
          <div className="assign">
            <select
              className="field"
              value={film}
              onChange={(e) => setFilm(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Фильм…</option>
              {available.map((f) => (
                <option key={f.id} value={f.id!}>
                  {f.title_ru}
                </option>
              ))}
            </select>
            <select
              className="field"
              value={slot}
              onChange={(e) => setSlot(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Вечер…</option>
              {slots.map((s) => (
                <option key={s.id} value={s.id}>
                  {dayLabel(s.starts_at)}
                </option>
              ))}
            </select>
            <button
              className="mark mark--wishlist is-on"
              disabled={busy || film === "" || slot === ""}
              onClick={() =>
                act(async () => {
                  await assignScreening(Number(film), Number(slot));
                  setFilm("");
                  setSlot("");
                })
              }
            >
              Назначить
            </button>
          </div>

          {placed.length > 0 && (
            <button className="primary" disabled={busy} onClick={() => act(publishSchedule)}>
              Опубликовать расписание
            </button>
          )}
          <p className="hint">
            После публикации всем, кто голосовал за назначенные фильмы, уйдёт приглашение,
            и они смогут подтвердить приход.
          </p>
        </>
      )}
    </>
  );
}

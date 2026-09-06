import { useEffect, useState } from "react";
import { getFilmStats } from "../api";
import { Bars } from "./Bars";
import type { FilmStats } from "../types";

function day(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) : "—";
}

/** Статистика фильма для администратора (§14).
 *
 * Отвечает на единственный вопрос, который возникает над списком: почему этот
 * фильм здесь и что с ним было раньше. Открыта в любой момент, а не только
 * на отборе, — вопрос возникает не по расписанию.
 */
export function FilmStatsPanel({ filmId }: { filmId: number }) {
  const [stats, setStats] = useState<FilmStats | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    getFilmStats(filmId)
      .then((data) => alive && setStats(data))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [filmId]);

  // Молча: обычный участник сюда просто не имеет доступа, и это не ошибка.
  if (error) return null;
  if (!stats) return <p className="hint">Считаем статистику…</p>;

  return (
    <>
      <div className="stats-grid">
        <div className="stat">
          <b>{stats.weight}</b>
          <span>вес</span>
        </div>
        <div className="stat">
          <b>{stats.wishlist_count}</b>
          <span>🟣 желаемое</span>
        </div>
        <div className="stat">
          <b>{stats.soon_count}</b>
          <span>🟠 ближайшее</span>
        </div>
        <div className="stat">
          <b>{stats.long_wait_count}</b>
          <span>ждут &gt; {stats.long_wait_days} дн.</span>
        </div>
        <div className="stat">
          <b>{stats.shortlist_misses}</b>
          <span>в шорт-листе без показа</span>
        </div>
        <div className="stat">
          <b>{stats.internal_rating ?? "—"}</b>
          <span>клуб · {stats.internal_votes} оц.</span>
        </div>
      </div>

      {stats.dynamics.length > 0 && (
        <>
          <h3>Динамика интереса</h3>
          <Bars
            data={stats.dynamics.map((point) => ({
              label: day(point.week_start),
              value: point.wishlist,
              extra: point.soon,
            }))}
            hint="По неделям: синим — «Желаемое», оранжевым — «Ближайшее». Считается по моменту отметки, а не по её нынешнему состоянию."
          />
        </>
      )}

      {stats.history.length > 0 && (
        <>
          <h3>Показы</h3>
          {stats.history.map((record) => (
            <div className="funnel-row" key={record.screening_id}>
              <span>{day(record.starts_at)}</span>
              <b>
                {record.came}
                {record.expected !== null && ` из ${record.expected}`}
              </b>
              <span className="hint">
                {record.status === "cancelled" ? "отменён" : record.rating ?? ""}
              </span>
            </div>
          ))}
          <p className="hint">Пришли из ожидавшихся; справа — оценка клуба.</p>
        </>
      )}
    </>
  );
}

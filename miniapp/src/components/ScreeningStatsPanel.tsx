import { useEffect, useState } from "react";
import { getScreeningStats } from "../api";
import type { ScreeningStats } from "../types";

function People({ title, people }: { title: string; people: ScreeningStats["waitlist"] }) {
  if (people.length === 0) return null;
  return (
    <>
      <h3>
        {title} · {people.length}
      </h3>
      {people.map((person) => (
        <div className="funnel-row" key={person.user_id}>
          <span>{person.display_name}</span>
          <b />
          <span className="hint">{person.detail ?? ""}</span>
        </div>
      ))}
    </>
  );
}

/** Всё про один сеанс (§14).
 *
 * До показа отвечает на «сколько придёт и хватит ли кворума», после —
 * на «кто пришёл и кто подтвердил, но не явился». Обновляется сама: в зале
 * список меняется на глазах.
 */
export function ScreeningStatsPanel({ screeningId }: { screeningId: number }) {
  const [stats, setStats] = useState<ScreeningStats | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;

    function load() {
      getScreeningStats(screeningId)
        .then((data) => alive && setStats(data))
        .catch(() => alive && setError(true));
    }

    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [screeningId]);

  if (error) return null;
  if (!stats) return <p className="hint">Считаем…</p>;

  return (
    <>
      {stats.low_attendance_warning && (
        <div className="warn">
          Подтвердили {stats.confirmed}, кворум {stats.min_attendance}. До начала осталось
          немного — решение о проведении за вами.
        </div>
      )}

      <div className="stats-grid">
        <div className="stat">
          <b>{stats.confirmed}</b>
          <span>придут</span>
        </div>
        <div className="stat">
          <b>{stats.fill_rate}%</b>
          <span>зал на {stats.capacity}</span>
        </div>
        <div className="stat">
          <b>{stats.attended.length}</b>
          <span>отметились</span>
        </div>
        <div className="stat">
          <b>{stats.waitlist.length}</b>
          <span>в очереди</span>
        </div>
        <div className="stat">
          <b>{stats.cancelled}</b>
          <span>отменили · {stats.late_cancels} поздно</span>
        </div>
        <div className="stat">
          <b>{stats.started ? stats.no_shows.length : "—"}</b>
          <span>не пришли</span>
        </div>
      </div>

      {(stats.film_rating !== null ||
        stats.visit_rating !== null ||
        stats.discussion_rating !== null) && (
        <div className="stats-grid">
          <div className="stat">
            <b>{stats.film_rating ?? "—"}</b>
            <span>фильм · {stats.film_rating_votes} оц.</span>
          </div>
          {/* §8: впечатление от вечера и от обсуждения — отдельные числа,
              в рейтинг фильма они не входят. */}
          <div className="stat">
            <b>{stats.visit_rating ?? "—"}</b>
            <span>вечер · {stats.visit_rating_votes} оц.</span>
          </div>
          <div className="stat">
            <b>{stats.discussion_rating ?? "—"}</b>
            <span>обсуждение · {stats.discussion_rating_votes} оц.</span>
          </div>
        </div>
      )}

      <People title="В очереди" people={stats.waitlist} />
      <People title="Подтвердили и не пришли" people={stats.no_shows} />
    </>
  );
}

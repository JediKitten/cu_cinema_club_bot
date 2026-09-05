import { useEffect, useState } from "react";
import { getAnalytics } from "../api";
import { weekLabel } from "../dates";
import type { Analytics as Data, FunnelStep } from "../types";

/** Воронка §14: важны переходы, а не абсолютные числа.
 *
 * Провал между голосованием и подтверждением означает неудобные слоты, между
 * подтверждением и явкой — что подтверждение не воспринимают всерьёз. Поэтому
 * рядом с числом показываем долю от предыдущего шага.
 */
function share(current: number, previous: number): string {
  if (previous === 0) return "—";
  return `${Math.round((current / previous) * 100)}%`;
}

function Funnel({ step }: { step: FunnelStep }) {
  const rows: [string, number, number | null][] = [
    ["Отметили интерес", step.interested, null],
    ["Проголосовали", step.voted, step.interested],
    ["Подтвердили", step.confirmed, step.voted],
    ["Пришли", step.attended, step.confirmed],
  ];

  return (
    <div className="round-head">
      <b>Неделя {weekLabel(step.week_start)}</b>
      {rows.map(([label, value, previous]) => (
        <div className="funnel-row" key={label}>
          <span>{label}</span>
          <b>{value}</b>
          <span className="hint">{previous === null ? "" : share(value, previous)}</span>
        </div>
      ))}
    </div>
  );
}

export function Analytics() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAnalytics()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="hint">Загрузка аналитики…</p>;

  const { overview } = data;

  return (
    <>
      <h3>Воронка по неделям</h3>
      <p className="hint">
        Доля справа — от предыдущего шага. Провал между голосованием и подтверждением
        означает неудобные слоты, между подтверждением и явкой — что подтверждение
        не воспринимают всерьёз.
      </p>
      {data.funnel.length === 0 && <p className="hint">Циклов ещё не было.</p>}
      {data.funnel.map((step) => (
        <Funnel key={step.week_start} step={step} />
      ))}

      <h3>Итоги</h3>
      <div className="ratings">
        <div className="rating">
          <b>{overview.average_attendance}</b>
          <span>средняя явка</span>
        </div>
        <div className="rating">
          <b>{overview.hall_fill_rate}%</b>
          <span>заполнение зала</span>
        </div>
        <div className="rating">
          <b>{overview.no_show_rate}%</b>
          <span>не пришли</span>
        </div>
        <div className="rating">
          <b>{overview.active_users}</b>
          <span>активных</span>
        </div>
        <div className="rating">
          <b>{overview.screenings_held}</b>
          <span>показов прошло</span>
        </div>
        <div className="rating">
          <b>{overview.screenings_cancelled}</b>
          <span>отменено</span>
        </div>
      </div>

      {Object.keys(overview.by_weekday).length > 0 && (
        <>
          <h3>Явка по дням</h3>
          {Object.entries(overview.by_weekday).map(([day, value]) => (
            <div className="funnel-row" key={day}>
              <span>{day}</span>
              <b>{value}</b>
              <span />
            </div>
          ))}
        </>
      )}

      {overview.long_wait_films.length > 0 && (
        <>
          <h3>Давно ждут</h3>
          {overview.long_wait_films.map((film) => (
            <div className="funnel-row" key={film.title}>
              <span>
                {film.title} {film.year && `(${film.year})`}
              </span>
              <b>{film.waiting}</b>
              <span className="hint">{film.days} дн.</span>
            </div>
          ))}
        </>
      )}

      {data.top_rated.length > 0 && (
        <>
          <h3>Рейтинг клуба</h3>
          {data.top_rated.map((film) => (
            <div className="funnel-row" key={film.title}>
              <span>{film.title}</span>
              <b>{film.rating}</b>
              <span className="hint">{film.votes} оц.</span>
            </div>
          ))}
        </>
      )}
    </>
  );
}

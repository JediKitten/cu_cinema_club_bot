import { useEffect, useState } from "react";
import { getAnalytics } from "../api";
import { Bars } from "./Bars";
import { Section } from "./Section";
import { weekLabel } from "../dates";
import type { Analytics as Data, FunnelStep } from "../types";

/** Воронка §14: важны переходы, а не абсолютные числа.
 *
 * Провал между голосованием и подтверждением означает неудобные слоты, между
 * подтверждением и явкой — что подтверждение не воспринимают всерьёз. Поэтому
 * рядом с числом показываем долю от предыдущего шага.
 */
function shortDay(iso: string): string {
  const at = new Date(`${iso}T00:00:00`);
  return `${at.getDate()}.${at.getMonth() + 1}`;
}

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
      <Section
        title="Воронка по неделям"
        count={data.funnel.length}
        storageKey="stats-funnel"
        hint="Доля справа — от предыдущего шага. Провал между голосованием и подтверждением означает неудобные слоты, между подтверждением и явкой — что подтверждение не воспринимают всерьёз."
      >
        {data.funnel.length === 0 && <p className="hint">Циклов ещё не было.</p>}
        {data.funnel.map((step) => (
          <Funnel key={step.week_start} step={step} />
        ))}
      </Section>

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
          <span>отменено · {overview.cancelled_share}%</span>
        </div>
        <div className="rating">
          <b>{overview.late_cancels}</b>
          <span>поздних отмен</span>
        </div>
      </div>

      {overview.audience_by_week.length > 0 && (
        <>
          <h3>Активная аудитория</h3>
          <Bars
            data={overview.audience_by_week.map((point) => ({
              // Под столбиком помещается только дата понедельника — полная
              // подпись недели («7–13 сентября») превратила бы ось в кашу.
              label: shortDay(point.week_start),
              value: point.people,
            }))}
            hint="Сколько разных людей за неделю отметили фильм, проголосовали, подтвердили приход или пришли."
          />
        </>
      )}

      {(overview.soon_churn.people ?? 0) > 0 && (
        <>
          <h3>Отток «Ближайшего»</h3>
          <div className="stats-grid">
            <div className="stat">
              <b>{overview.soon_churn.expired_marks ?? 0}</b>
              <span>отметок истекло</span>
            </div>
            <div className="stat">
              <b>{overview.soon_churn.people ?? 0}</b>
              <span>у скольких людей</span>
            </div>
            <div className="stat">
              <b>{overview.soon_churn.lapsed ?? 0}</b>
              <span>не вернулись</span>
            </div>
          </div>
          <p className="hint">
            Отметка не сгорает, а становится «Желаемым». «Не вернулись» — те, у кого
            срок вышел и ни одного свежего «Ближайшего» больше нет.
          </p>
        </>
      )}

      {overview.no_show_users.length > 0 && (
        <Section title="Подтверждают и не приходят" storageKey="stats-noshow" defaultOpen={false}>
          {overview.no_show_users.map((person) => (
            <div className="funnel-row" key={person.user_id}>
              <span>{person.display_name}</span>
              <b>{person.misses}</b>
              <span className="hint">раз</span>
            </div>
          ))}
        </Section>
      )}

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

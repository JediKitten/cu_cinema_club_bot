import { useEffect, useState } from "react";
import { ApiError, getAnalytics, getExportPassword, saveExportPassword } from "../api";
import { Bars } from "./Bars";
import { Section } from "./Section";
import { weekLabel } from "../dates";
import { showMessage } from "../telegram";
import type { CsatWeek, ExportPassword, FunnelStep } from "../types";
import { useLoad } from "../useLoad";

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

/** Пароль на команду /analytics в боте.
 *
 * Графики выше отвечают на вопросы, которые мы придумали заранее; сырые
 * таблицы нужны для всех остальных. Заказывают их в боте, а не здесь: файл
 * приходит в переписку, откуда его сразу перешлют куда надо.
 *
 * Пароль отдельный от ролей намеренно: таблицы бывают нужны тем, кому админка
 * не нужна вовсе, а выдавать ради выгрузки роль админа значит выдавать заодно
 * отмену показов и правку параметров.
 */
function ExportAccess() {
  const [state, setState] = useState<ExportPassword | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getExportPassword()
      .then(setState)
      .catch(() => setState({ is_set: false, updated_at: null, updated_by: null }));
  }, []);

  async function save(password: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setState(await saveExportPassword(password));
      setDraft("");
      showMessage(password ? "Пароль обновлён" : "Выгрузка выключена");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не получилось сохранить");
    } finally {
      setBusy(false);
    }
  }

  if (!state) return null;

  const changed = new Date(state.updated_at ?? 0);

  return (
    <Section
      title="Выгрузка в Excel"
      storageKey="stats-export"
      defaultOpen={false}
      hint="Команда /analytics в боте: человек вводит пароль и выбирает, какие таблицы скачать. Пароль знает только тот, кому вы его передали, — роль админа для этого не нужна."
    >
      <p className="hint">
        {state.is_set
          ? `Пароль задан${state.updated_by ? `, поставил ${state.updated_by}` : ""}${
              state.updated_at ? ` ${changed.toLocaleDateString("ru-RU")}` : ""
            }.`
          : "Пароль не задан — команда никому ничего не отдаёт."}
      </p>

      <input
        className="field"
        type="password"
        autoComplete="new-password"
        placeholder="Новый пароль, от 8 символов"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      {error && <div className="error">{error}</div>}

      <div className="marks">
        <button
          className="primary"
          disabled={busy || draft.trim().length < 8}
          onClick={() => save(draft.trim())}
        >
          {state.is_set ? "Сменить пароль" : "Включить выгрузку"}
        </button>
        {state.is_set && (
          <button className="mark" disabled={busy} onClick={() => save("")}>
            Выключить
          </button>
        )}
      </div>

      <p className="hint">
        Показать действующий пароль нельзя: в базе лежит только его отпечаток.
        Забыли — поставьте новый. Старый после этого перестанет работать.
      </p>
    </Section>
  );
}

const STARS = (value: number) => value.toFixed(1).replace(".", ",");

/** Опрос после показов по неделям — то, чем клуб отчитывается перед вузом.
 *
 *  Три графика, а не один: общий CSAT говорит «стало хуже», а вечер и
 *  обсуждение по отдельности — что именно. Шкала у всех одна, до пяти звёзд,
 *  иначе 3,8 выглядело бы полным столбиком. Под датой — сколько ответили:
 *  5,0 от двоих и 5,0 от тридцати — разные новости. */
function CsatByWeek({ weeks }: { weeks: CsatWeek[] }) {
  const chart = (pick: (week: CsatWeek) => [number | null, number]) =>
    weeks.map((week) => {
      const [value, votes] = pick(week);
      return { label: shortDay(week.week_start), value, note: votes ? `${votes} отв.` : "" };
    });

  return (
    <>
      <h3>CSAT по неделям</h3>
      <Bars
        data={chart((week) => [week.overall, week.overall_votes])}
        max={5}
        format={STARS}
        hint="Общий: у каждого ответа — среднее из «вечера» и «обсуждения», затем среднее за неделю. Фильм сюда не входит. Неделя — по дате показа."
      />
      <h4 className="chart-title">Вечер в целом</h4>
      <Bars data={chart((week) => [week.visit, week.visit_votes])} max={5} format={STARS} />
      <h4 className="chart-title">Обсуждение после фильма</h4>
      <Bars
        data={chart((week) => [week.discussion, week.discussion_votes])}
        max={5}
        format={STARS}
        hint="Ответы «не был» и «затрудняюсь» в обсуждение не входят."
      />
    </>
  );
}

export function Analytics() {
  const { data, error } = useLoad(getAnalytics, []);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="hint">Загрузка аналитики…</p>;

  const { overview } = data;

  return (
    <>
      <ExportAccess />

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

      {overview.csat_by_week.length > 0 && <CsatByWeek weeks={overview.csat_by_week} />}

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

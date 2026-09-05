import { useEffect, useState } from "react";
import { Matrix } from "../components/Matrix";
import {
  blockSlot,
  getRankings,
  getRound,
  openRound,
  publishShortlist,
  saveShortlist,
} from "../api";
import { Poster } from "../components/FilmRow";
import { haptic } from "../telegram";
import type { RankRow, Rankings, Round, Slot } from "../types";

type Tab = "weight" | "coverage";

const STAGE_LABEL: Record<string, string> = {
  collecting: "Собираем интерес",
  shortlist_review: "Шорт-лист собран, не опубликован",
  slot_voting: "Идёт голосование за фильмы и вечера",
  schedule_review: "Расставляем показы",
  published: "Расписание опубликовано",
  running: "Неделя показов",
  closed: "Закрыт",
};

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function slotLabel(slot: Slot): string {
  const at = new Date(slot.starts_at);
  // Сервер отдаёт UTC; toLocale* переводит в зону устройства — для студентов
  // одного вуза это и есть нужная зона.
  const weekday = WEEKDAYS[(at.getDay() + 6) % 7];
  const time = at.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `${weekday}, ${at.getDate()}.${String(at.getMonth() + 1).padStart(2, "0")} ${time}`;
}

export function Admin() {
  const [round, setRound] = useState<Round | null>(null);
  const [rankings, setRankings] = useState<Rankings | null>(null);
  const [tab, setTab] = useState<Tab>("coverage");
  const [picked, setPicked] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [currentRound, ranks] = await Promise.all([getRound(), getRankings()]);
        setRound(currentRound);
        setRankings(ranks);
        setPicked(currentRound?.shortlist.map((item) => item.film_id) ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не удалось загрузить");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function act<T>(action: () => Promise<T>, apply: (result: T) => void) {
    setBusy(true);
    setError(null);
    try {
      apply(await action());
      haptic();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  function toggle(filmId: number) {
    setPicked((current) =>
      current.includes(filmId)
        ? current.filter((id) => id !== filmId)
        : [...current, filmId],
    );
    haptic();
  }

  if (loading) return <div className="center">Загрузка…</div>;

  const locked = round !== null && round.stage !== "collecting" && round.stage !== "shortlist_review";
  const rows: RankRow[] = (tab === "weight" ? rankings?.by_weight : rankings?.by_coverage) ?? [];
  const autopilot = new Set(round?.autopilot_film_ids ?? []);
  const dirty =
    round !== null &&
    JSON.stringify(picked) !== JSON.stringify(round.shortlist.map((i) => i.film_id));

  return (
    <div className="screen">
      {error && <div className="error">{error}</div>}

      {round === null ? (
        <>
          <p className="hint">Активного цикла нет. Откройте цикл на следующую неделю.</p>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              act(openRound, (created) => {
                setRound(created);
                setPicked([]);
              })
            }
          >
            Открыть цикл
          </button>
        </>
      ) : (
        <>
          <div className="round-head">
            <b>Неделя с {new Date(round.week_start).toLocaleDateString("ru-RU")}</b>
            <p className="meta">{STAGE_LABEL[round.stage] ?? round.stage}</p>
            {round.low_activity && (
              <p className="badge">Низкая активность: фильмов выше порога меньше нужного</p>
            )}
          </div>

          <div className="tabs-inline">
            {(["coverage", "weight"] as Tab[]).map((key) => (
              <button
                key={key}
                className={`mark ${tab === key ? "is-on mark--wishlist" : ""}`}
                onClick={() => setTab(key)}
              >
                {key === "coverage" ? "По охвату" : "По весу"}
              </button>
            ))}
          </div>
          <p className="hint">
            {tab === "coverage"
              ? "Жадный отбор: каждый следующий фильм приводит новых людей, а не тех же самых."
              : "Простая сумма весов отметок."}
          </p>

          {rows.length === 0 && <p className="hint">Пока никто ничего не отметил.</p>}

          {rows.map((row) => {
            const chosen = picked.includes(row.film_id);
            return (
              <div className="film-row" key={row.film_id}>
                <Poster url={row.poster_url} />
                <div>
                  <p className="film-row__title">{row.title_ru}</p>
                  <p className="meta">
                    {row.year} · вес {row.weight}
                    {row.marginal_weight !== null && ` · прирост ${row.marginal_weight}`}
                  </p>
                  <p className="meta">
                    🟣 {row.wishlist_count} · 🟠 {row.soon_count}
                    {row.long_wait_count > 0 && ` · давно ждут: ${row.long_wait_count}`}
                  </p>
                  <div className="marks">
                    <button
                      className={`mark ${chosen ? "is-on mark--wishlist" : ""}`}
                      disabled={locked}
                      onClick={() => toggle(row.film_id)}
                    >
                      {chosen ? "✓ В шорт-листе" : "В шорт-лист"}
                    </button>
                    {autopilot.has(row.film_id) && <span className="badge">выбор автопилота</span>}
                  </div>
                </div>
              </div>
            );
          })}

          {!locked && (
            <>
              {picked.length > 0 && (
                <button
                  className="primary"
                  disabled={busy || !dirty}
                  onClick={() =>
                    act(
                      () => saveShortlist(picked),
                      (updated) => setRound(updated),
                    )
                  }
                >
                  {dirty ? `Сохранить шорт-лист (${picked.length})` : "Шорт-лист сохранён"}
                </button>
              )}

              {round.shortlist.length > 0 && (
                <>
                  <button
                    className="primary"
                    disabled={busy || dirty}
                    onClick={() => act(publishShortlist, (updated) => setRound(updated))}
                  >
                    Опубликовать и открыть голосование
                  </button>
                  {dirty && (
                    <p className="hint">Сначала сохраните изменения, потом публикуйте.</p>
                  )}
                </>
              )}
            </>
          )}

          {(round.stage === "slot_voting" || round.stage === "schedule_review") && (
            <>
              <h3>Матрица «фильм × вечер»</h3>
              <Matrix />
            </>
          )}

          <h3>Вечера</h3>
          <p className="hint">Заблокированные вечера автопилот не использует.</p>
          {round.slots.map((slot) => (
            <div className="film-row" key={slot.id} style={{ gridTemplateColumns: "1fr auto" }}>
              <div>
                <p className="film-row__title" style={{ marginBottom: 2 }}>
                  {slotLabel(slot)}
                </p>
                <p className="meta">
                  {slot.blocked ? "Закрыт" : "Открыт"} · {slot.hall_name} · до{" "}
                  {slot.hall_capacity} мест
                  {slot.blocked_reason && ` · ${slot.blocked_reason}`}
                </p>
              </div>
              {/* На кнопке — действие, а не текущее состояние. Раньше здесь было
                  «Открыт»/«Закрыт», и это читалось как команда: вечера закрывали,
                  думая, что открывают. Состояние теперь видно по строке слева. */}
              <button
                className={`mark ${slot.blocked ? "mark--wishlist is-on" : "mark--soon is-on"}`}
                disabled={busy}
                title={slot.blocked ? "Вернуть вечер в расписание" : "Убрать вечер из расписания"}
                onClick={() =>
                  act(
                    () =>
                      blockSlot(
                        slot.id,
                        !slot.blocked,
                        slot.blocked ? undefined : "закрыт администратором",
                      ),
                    (updated) => setRound(updated),
                  )
                }
              >
                {slot.blocked ? "Открыть" : "Закрыть"}
              </button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

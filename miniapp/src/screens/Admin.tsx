import { useEffect, useState } from "react";
import { useOpenFilmById } from "../filmOpener";
import { Analytics } from "../components/Analytics";
import { EventPanel } from "../components/EventPanel";
import { SettingsPanel } from "../components/SettingsPanel";
import { TeamPanel } from "../components/TeamPanel";
import { InvitePanel } from "../components/InvitePanel";
import { PeoplePanel } from "../components/PeoplePanel";
import { Matrix } from "../components/Matrix";
import { Section } from "../components/Section";
import { ScheduleBuilder } from "../components/ScheduleBuilder";
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
import type { RankRow, Rankings, Round, ScreeningRecord, Slot, User } from "../types";

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

function showLabel(record: ScreeningRecord): string {
  const day = record.starts_at
    ? new Date(record.starts_at).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
    : "—";
  if (record.status === "cancelled") return `${day} (отменён)`;
  // Пришло из ожидавшихся: одно это сравнение и говорит, стоил ли показ вечера.
  return record.expected !== null
    ? `${day} — ${record.came} из ${record.expected}`
    : `${day} — ${record.came}`;
}

function windowNotice(round: Round): string {
  const opens = new Date(round.shortlist_window_opens_at!);
  const closes = new Date(round.shortlist_window_closes_at!);
  const clock = (at: Date) =>
    at.toLocaleString("ru-RU", {
      weekday: "short",
      day: "numeric",
      month: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  return Date.now() < opens.getTime()
    ? `Шорт-лист собирают с ${clock(opens)} до ${clock(closes)} — пока только смотрим.`
    : `Окно сборки закрылось ${clock(closes)}: список ушёл в голосование.`;
}

type Panel = "round" | "events" | "stats" | "team" | "invites" | "people" | "settings";

// Порядок ролей тот же, что на сервере: вкладка, которую нельзя открыть,
// не должна и показываться — иначе она встречает ошибкой доступа.
const RANK: Record<string, number> = { user: 0, moderator: 1, admin: 2, superadmin: 3 };

const PANELS: { key: Panel; label: string; minRole: keyof typeof RANK }[] = [
  { key: "round", label: "Цикл", minRole: "moderator" },
  { key: "events", label: "События", minRole: "admin" },
  { key: "stats", label: "Аналитика", minRole: "admin" },
  { key: "team", label: "Команда", minRole: "admin" },
  { key: "invites", label: "Коды", minRole: "admin" },
  { key: "people", label: "Люди", minRole: "superadmin" },
  { key: "settings", label: "Параметры", minRole: "superadmin" },
];

export function Admin({ me }: { me: User }) {
  const role = me.role;
  const [panel, setPanel] = useState<Panel>("round");
  const openFilm = useOpenFilmById();
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
        // Рейтинги — админские, цикл видит и модератор: одна недоступная
        // ручка не должна оставлять его с пустым экраном.
        const [currentRound, ranks] = await Promise.all([
          getRound(),
          getRankings().catch(() => null),
        ]);
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

  const stageLocked =
    round !== null && round.stage !== "collecting" && round.stage !== "shortlist_review";
  // Собирать шорт-лист руками можно только в окне (решение клуба): до среды
  // веса ещё набираются, после четверга список уходит в голосование.
  const windowOpen = round?.shortlist_window_open ?? false;
  const locked = stageLocked || !windowOpen;
  const rows: RankRow[] = (tab === "weight" ? rankings?.by_weight : rankings?.by_coverage) ?? [];
  const autopilot = new Set(round?.autopilot_film_ids ?? []);
  const dirty =
    round !== null &&
    JSON.stringify(picked) !== JSON.stringify(round.shortlist.map((i) => i.film_id));

  const panels = PANELS.filter((item) => RANK[role] >= RANK[item.minRole]);

  return (
    <div className="screen">
      <div className="tabs-inline">
        {panels.map((item) => (
          <button
            key={item.key}
            className={`mark ${panel === item.key ? "is-on mark--wishlist" : ""}`}
            onClick={() => setPanel(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {panel === "team" && <TeamPanel me={me} />}
      {panel === "invites" && <InvitePanel isSuperadmin={role === "superadmin"} />}
      {panel === "people" && <PeoplePanel />}
      {panel === "settings" && <SettingsPanel />}
      {panel === "events" && <EventPanel onCreated={() => setPanel("round")} />}
      {panel === "stats" && <Analytics />}
      {error && <div className="error">{error}</div>}

      {panel === "round" && (round === null ? (
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

          {!stageLocked && !windowOpen && round.shortlist_window_opens_at && (
            <p className="badge">{windowNotice(round)}</p>
          )}

          {rows.length === 0 && <p className="hint">Пока никто ничего не отметил.</p>}

          <Section title="Фильмы" count={rows.length} storageKey="admin-rankings">
          {rows.map((row) => {
            const chosen = picked.includes(row.film_id);
            return (
              <div
                className="film-row film-row--clickable"
                key={row.film_id}
                onClick={() => openFilm(row.film_id, row.title_ru)}
              >
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
                  {/* Три числа принципиально разные, поэтому в одну оценку
                      их не сводим (§11): внешний рейтинг, рейтинг клуба и то,
                      сколько раз фильм оставался без вечера. */}
                  <p className="meta">
                    {row.ext_rating !== null && `TMDB ${row.ext_rating}`}
                    {row.internal_rating !== null &&
                      ` · клуб ${row.internal_rating} (${row.internal_votes})`}
                    {row.shortlist_misses > 0 && ` · без вечера: ${row.shortlist_misses}`}
                  </p>
                  {row.screening_history.length > 0 && (
                    <p className="meta">
                      уже показывали:{" "}
                      {row.screening_history
                        .slice(0, 3)
                        .map((record) => showLabel(record))
                        .join(", ")}
                    </p>
                  )}
                  <div className="marks">
                    <button
                      className={`mark ${chosen ? "is-on mark--wishlist" : ""}`}
                      disabled={locked}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggle(row.film_id);
                      }}
                    >
                      {chosen ? "✓ В шорт-листе" : "В шорт-лист"}
                    </button>
                    {autopilot.has(row.film_id) && <span className="badge">выбор автопилота</span>}
                  </div>
                </div>
              </div>
            );
          })}
          </Section>

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
            <Section title="Матрица «фильм × вечер»" storageKey="admin-matrix">
              <Matrix />
            </Section>
          )}

          {round.stage !== "collecting" && round.stage !== "shortlist_review" && (
            <Section title="Показы" storageKey="admin-screenings">
              <ScheduleBuilder shortlist={round.shortlist.map((item) => item.film)} />
            </Section>
          )}

          <Section
            title="Вечера"
            count={round.slots.length}
            storageKey="admin-slots"
            hint="Заблокированные вечера автопилот не использует."
          >
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
          </Section>
        </>
      ))}
    </div>
  );
}

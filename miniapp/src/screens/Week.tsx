import { useState } from "react";
import { getSchedule } from "../api";
import { shiftWeek, weekLabel } from "../dates";
import { TournamentBanner } from "../components/TournamentBanner";
import { haptic } from "../telegram";
import { useLoad } from "../useLoad";
import { Screenings } from "./Screenings";
import { Vote } from "./Vote";

/** Раздел «Расписание».
 *
 * Показывает то, что сейчас требуется от человека: идёт голосование — бюллетень,
 * иначе показы недели. По неделям можно листать: расписание — это не только
 * ближайшие дни, но и то, что уже было и что будет.
 */
/** Неделя из адреса: кнопка под уведомлением в боте открывает приложение
 * сразу на бюллетене, а не на расписании текущей недели с плашкой «идёт
 * голосование» — человек уже отметил фильмы в чате и пришёл за вечерами. */
function requestedWeek(): string | null {
  const raw = new URLSearchParams(location.search).get("week");
  return raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : null;
}

export function Week({ onOpenTournament }: { onOpenTournament(id: number): void }) {
  const [week, setWeek] = useState<string | null>(requestedWeek);
  // Первый запрос уходит без недели — её выбирает сервер. Запоминать её
  // в `week` незачем: это вызвало бы вторую загрузку той же недели, а стрелки
  // и так сдвигаются от `schedule.week_start`.
  const {
    data: schedule,
    setData: setSchedule,
    loading,
    error,
  } = useLoad(() => getSchedule(week ?? undefined), [week]);

  function go(delta: number) {
    if (!schedule) return;
    haptic();
    setWeek(shiftWeek(schedule.week_start, delta));
  }

  // Голосование привязано к активному циклу, а не к листаемой неделе: показывать
  // бюллетень на чужой неделе значило бы предлагать выбрать вечера не той недели.
  const voting = schedule?.stage === "slot_voting";
  const empty = schedule?.screenings.every((item) => item.status === "cancelled") ?? false;

  return (
    <div className="screen">
      <TournamentBanner onOpen={onOpenTournament} />

      <div className="week-nav">
        <button
          className="week-nav__arrow"
          disabled={loading || !schedule?.has_prev}
          onClick={() => go(-1)}
          aria-label="Предыдущая неделя"
        >
          ‹
        </button>
        <b>{schedule ? weekLabel(schedule.week_start) : "…"}</b>
        <button
          className="week-nav__arrow"
          disabled={loading || !schedule?.has_next}
          onClick={() => go(1)}
          aria-label="Следующая неделя"
        >
          ›
        </button>
      </div>

      {schedule?.voting_week && !empty && (
        // Голосование — единственное, что требует действия. Оно идёт на другой
        // неделе, поэтому ведём туда явно, а не надеемся, что долистают.
        // На пустой неделе плашки нет: там то же самое говорит сам экран,
        // подробнее и без повтора в двух строчках подряд.
        <button className="notice" onClick={() => setWeek(schedule.voting_week)}>
          Идёт выбор фильмов на неделю {weekLabel(schedule.voting_week)} →
        </button>
      )}

      {error && <div className="error">{error}</div>}
      {loading && !schedule && <div className="center">Загрузка…</div>}

      {schedule && voting && <Vote />}
      {schedule && !voting && (
        <Screenings
          schedule={schedule}
          onChange={setSchedule}
          onGoToVoting={
            schedule.voting_week ? () => setWeek(schedule.voting_week) : undefined
          }
        />
      )}
    </div>
  );
}

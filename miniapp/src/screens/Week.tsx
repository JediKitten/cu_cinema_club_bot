import { useEffect, useState } from "react";
import { ApiError, getSchedule } from "../api";
import { shiftWeek, weekLabel } from "../dates";
import { TournamentBanner } from "../components/TournamentBanner";
import { haptic } from "../telegram";
import type { Schedule } from "../types";
import { Screenings } from "./Screenings";
import { Vote } from "./Vote";

/** Раздел «Расписание».
 *
 * Показывает то, что сейчас требуется от человека: идёт голосование — бюллетень,
 * иначе показы недели. По неделям можно листать: расписание — это не только
 * ближайшие дни, но и то, что уже было и что будет.
 */
export function Week({ onOpenTournament }: { onOpenTournament(id: number): void }) {
  const [week, setWeek] = useState<string | null>(null);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getSchedule(week ?? undefined)
      .then((next) => {
        if (!alive) return;
        setSchedule(next);
        // Первый запрос приходит без недели — запоминаем ту, что выбрал сервер,
        // иначе стрелки некуда было бы сдвигать.
        if (week === null) setWeek(next.week_start);
        setError(null);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof ApiError ? e.message : "Не удалось загрузить");
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [week]);

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

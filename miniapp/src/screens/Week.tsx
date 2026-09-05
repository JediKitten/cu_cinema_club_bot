import { useEffect, useState } from "react";
import { ApiError, getSchedule } from "../api";
import type { Schedule } from "../types";
import { Screenings } from "./Screenings";
import { Vote } from "./Vote";

/** Вкладка «Неделя» показывает то, что сейчас от человека требуется:
 *  идёт голосование — бюллетень, расписание опубликовано — подтверждения.
 *  Держать их в разных вкладках значило бы, что одна всегда пустует. */
export function Week() {
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSchedule()
      .then(setSchedule)
      .catch((error) => {
        // 404 — цикла нет, 409 — расписание ещё не опубликовано. И то и другое
        // означает «показывай голосование», а не ошибку.
        if (!(error instanceof ApiError) || ![404, 409].includes(error.status)) {
          throw error;
        }
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="center">Загрузка…</div>;
  if (schedule?.published) return <Screenings schedule={schedule} onChange={setSchedule} />;
  return <Vote />;
}

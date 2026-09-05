import { useEffect, useState } from "react";
import { getPastScreenings } from "../api";
import { Poster } from "../components/FilmRow";
import { dayLabel } from "../dates";
import type { PastScreening } from "../types";

/** Календарь прошедших показов (§18, пункт 10).
 *
 * Виден всем участникам: это память клуба, а не служебная статистика.
 * Ожидаемая явка рядом с фактической показывает, насколько прогноз сошёлся.
 */
export function History() {
  const [rows, setRows] = useState<PastScreening[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPastScreenings()
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  if (error) return <div className="screen"><div className="error">{error}</div></div>;
  if (!rows) return <div className="center">Загрузка…</div>;

  if (rows.length === 0) {
    return (
      <div className="center">
        <p>Показов ещё не было.</p>
        <p className="hint">Здесь будет история клуба: что смотрели и как это оценили.</p>
      </div>
    );
  }

  return (
    <div className="screen">
      <h3>Что уже смотрели</h3>
      {rows.map((row) => (
        <div className="film-row" key={row.screening_id}>
          <Poster url={row.poster_url} />
          <div>
            <p className="film-row__title">
              {row.title} {row.year && <span className="hint">({row.year})</span>}
            </p>
            <p className="meta">{dayLabel(row.starts_at)}</p>
            {/* Сюда попадают только состоявшиеся показы: отменённые никто
                не смотрел, и их сервер в этот список не отдаёт. */}
            <p className="meta">
              пришли {row.came}
              {row.expected !== null && ` из ожидаемых ${row.expected}`}
              {row.rating !== null && ` · оценка ${row.rating}`}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

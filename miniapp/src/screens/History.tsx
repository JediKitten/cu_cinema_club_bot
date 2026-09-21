import { useEffect, useState } from "react";
import { getPastScreenings } from "../api";
import { Poster } from "../components/FilmRow";
import { dayLabel } from "../dates";
import { useOpenFilmById } from "../filmOpener";
import type { PastScreening, Screening } from "../types";
import { Attend } from "./Attend";

/** Календарь прошедших показов (§18, пункт 10).
 *
 * Виден всем участникам: это память клуба, а не служебная статистика.
 * Ожидаемая явка рядом с фактической показывает, насколько прогноз сошёлся.
 */
export function History() {
  const openFilm = useOpenFilmById();
  const [rows, setRows] = useState<PastScreening[] | null>(null);
  const [survey, setSurvey] = useState<PastScreening | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPastScreenings()
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  if (survey) {
    // Опросу нужен показ в том виде, в каком его знает расписание. Из истории
    // приходит только карточка — остального форма и не спрашивает: человек
    // уже отмечен, ей остаётся задать четыре вопроса.
    const asScreening = {
      id: survey.screening_id,
      film: {
        id: survey.film_id,
        title_ru: survey.title,
        year: survey.year,
        poster_url: survey.poster_url,
      },
    } as unknown as Screening;
    return (
      <Attend
        screening={asScreening}
        onBack={() => setSurvey(null)}
        backLabel="← К показам"
      />
    );
  }

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
        <div
          className="film-row film-row--clickable"
          key={row.screening_id}
          onClick={() => openFilm(row.film_id, row.title)}
        >
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

            {/* Напоминание зовёт оценить показ — идти по нему должно быть
                куда. Кнопка есть только у того, кто здесь был: остальным
                отвечать не о чем. */}
            {row.i_attended && (
              <div className="marks">
                <button
                  className={`mark ${row.i_answered ? "" : "is-on mark--wishlist"}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSurvey(row);
                  }}
                >
                  {row.i_answered ? "Изменить ответы" : "Пройти опрос"}
                </button>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

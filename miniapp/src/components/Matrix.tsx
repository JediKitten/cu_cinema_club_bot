import { useEffect, useState } from "react";
import { getMatrix } from "../api";
import { weekdayShort } from "../dates";
import type { Matrix as MatrixData } from "../types";

/** Матрица «фильм × слот» (§6).
 *
 * В ячейке — сколько людей одновременно выбрали фильм и свободны в этот вечер.
 * Это и есть ожидаемая явка, если поставить показ сюда.
 */
export function Matrix() {
  const [data, setData] = useState<MatrixData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMatrix()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="hint">Загрузка матрицы…</p>;
  if (data.films.length === 0) return <p className="hint">Шорт-лист пуст.</p>;

  const cells = new Map(data.cells.map((c) => [`${c.film_id}:${c.slot_id}`, c.count]));
  const best = Math.max(1, ...data.cells.map((c) => c.count));

  return (
    <>
      <p className="hint">
        В ячейке — сколько человек и выбрали фильм, и свободны в этот вечер.
        Это ожидаемая явка, если назначить показ сюда.
      </p>

      {data.voters_without_evening > 0 && (
        // §6: такие голоса не попадут ни в одну ячейку.
        <div className="warn">
          {data.voters_without_evening} чел. выбрали фильмы, но не отметили ни одного
          вечера — их голоса ни на что не влияют.
        </div>
      )}

      {/* Таблица шире экрана телефона, поэтому скроллится по горизонтали внутри себя. */}
      <div className="matrix-scroll">
        <table className="matrix">
          <thead>
            <tr>
              <th className="matrix__corner">Фильм</th>
              {data.slots.map((slot) => (
                <th key={slot.id}>
                  {weekdayShort(slot.starts_at)}
                  <span className="matrix__sub">{data.slot_free[slot.id] ?? 0}</span>
                </th>
              ))}
              <th>всего</th>
            </tr>
          </thead>
          <tbody>
            {data.films.map((film) => (
              <tr key={film.id}>
                <th className="matrix__film" title={film.title_ru}>
                  {film.title_ru}
                </th>
                {data.slots.map((slot) => {
                  const value = cells.get(`${film.id}:${slot.id}`) ?? 0;
                  return (
                    <td
                      key={slot.id}
                      // Заливка по силе ячейки: глазами так видно лучший вечер
                      // быстрее, чем сравнением чисел.
                      style={{
                        background:
                          value > 0
                            ? `color-mix(in srgb, var(--link) ${(value / best) * 55}%, transparent)`
                            : undefined,
                      }}
                    >
                      {value || ""}
                    </td>
                  );
                })}
                <td className="matrix__total">{film.id ? (data.film_votes[film.id] ?? 0) : 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        Под днём недели — сколько человек свободны в этот вечер, в последнем
        столбце — сколько всего голосов у фильма.
      </p>
    </>
  );
}

import { getMatrix } from "../api";
import { weekdayShort } from "../dates";
import { useOpenFilm } from "../filmOpener";
import { useLoad } from "../useLoad";

/** Матрица «фильм × слот» (§6).
 *
 * В ячейке — сколько людей одновременно выбрали фильм и свободны в этот вечер.
 * Это и есть ожидаемая явка, если поставить показ сюда.
 */
export function Matrix() {
  const openFilm = useOpenFilm();
  const { data, error } = useLoad(getMatrix, []);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="hint">Загрузка матрицы…</p>;
  if (data.films.length === 0) return <p className="hint">Шорт-лист пуст.</p>;

  const cells = new Map(data.cells.map((c) => [`${c.film_id}:${c.slot_id}`, c.count]));
  const best = Math.max(1, ...data.cells.map((c) => c.count));
  const titles = new Map(data.films.map((film) => [film.id, film.title_ru]));
  const evenings = new Map(
    [...data.slots, ...data.blocked_slots].map((slot) => [slot.id, weekdayShort(slot.starts_at)]),
  );
  const sameChoice =
    data.autopilot.length === data.manual.length &&
    data.autopilot.every((a) =>
      data.manual.some((m) => m.film_id === a.film_id && m.slot_id === a.slot_id),
    );

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
                  <button className="matrix__link" onClick={() => openFilm(film)}>
                    {film.title_ru}
                  </button>
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

      {data.blocked_slots.length > 0 && (
        <>
          <h3>Закрытые вечера</h3>
          {data.blocked_slots.map((slot) => (
            <div className="funnel-row" key={slot.id}>
              <span>{weekdayShort(slot.starts_at)}</span>
              <b>{data.slot_free[slot.id] ?? 0}</b>
              <span className="hint">{slot.blocked_reason ?? "закрыт"}</span>
            </div>
          ))}
          {/* Блокировка выглядит бесплатной, пока не видно, скольких она стоит. */}
          <p className="hint">
            Рядом — сколько человек были свободны в этот вечер. Назначить на него нельзя.
          </p>
        </>
      )}

      {data.autopilot.length > 0 && (
        <>
          <h3>Автопилот</h3>
          <p className="hint">
            Решение считается всегда, даже когда расставляете руками, и ни на что не
            влияет до дедлайна (§5). Здесь оно только для сравнения.
          </p>
          {data.autopilot.map((item) => (
            <div className="funnel-row" key={`${item.film_id}:${item.slot_id}`}>
              <span>{titles.get(item.film_id) ?? `фильм ${item.film_id}`}</span>
              <b>{evenings.get(item.slot_id) ?? "—"}</b>
              <span className="hint">ждём {item.expected}</span>
            </div>
          ))}
          <div className="funnel-row">
            <span>Ожидаемая явка</span>
            <b>{data.autopilot_expected}</b>
            <span className="hint">
              {data.manual.length === 0
                ? "у вас пока пусто"
                : sameChoice
                  ? "совпадает с вашей расстановкой"
                  : `у вас ${data.manual_expected} (${
                      data.manual_expected >= data.autopilot_expected ? "+" : ""
                    }${data.manual_expected - data.autopilot_expected})`}
            </span>
          </div>
        </>
      )}
    </>
  );
}

const STARS = 5;

/** Пять звёзд с половинками.
 *
 * Каждая звезда — две зоны нажатия: левая ставит половину, правая целую.
 * На телефоне это надёжнее перетаскивания и точнее, чем ловить доли пикселя.
 * Повторное нажатие по своей же оценке снимает её.
 *
 * Половина рисуется обрезанной звездой поверх пустой, а не отдельным символом:
 * «⯪» есть не во всех шрифтах, и там, где его нет, оценка превращалась бы
 * в квадратик.
 */
export function StarRating({
  value,
  onChange,
  busy = false,
}: {
  value: number | null;
  onChange(next: number | null): void;
  busy?: boolean;
}) {
  function press(stars: number) {
    onChange(value === stars ? null : stars);
  }

  return (
    <div className="stars" role="group" aria-label="Ваша оценка">
      {Array.from({ length: STARS }, (_, index) => {
        const full = index + 1;
        const half = full - 0.5;
        const filled = value === null ? 0 : Math.min(1, Math.max(0, value - index));

        return (
          <span className="stars__star" key={full}>
            <span className="stars__empty" aria-hidden>
              ★
            </span>
            <span className="stars__fill" style={{ width: `${filled * 100}%` }} aria-hidden>
              ★
            </span>
            <button
              className="stars__half stars__half--left"
              disabled={busy}
              onClick={() => press(half)}
              aria-label={`${half} из ${STARS}`}
            />
            <button
              className="stars__half stars__half--right"
              disabled={busy}
              onClick={() => press(full)}
              aria-label={`${full} из ${STARS}`}
            />
          </span>
        );
      })}
      {value !== null && (
        <span className="stars__value">{value.toFixed(1).replace(".", ",")}</span>
      )}
    </div>
  );
}

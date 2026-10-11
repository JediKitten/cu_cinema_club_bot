type Bar = {
  label: string;
  /** Пусто — за этот период данных нет: столбика нет, вместо числа прочерк. */
  value: number | null;
  extra?: number;
  /** Мелкая строка под подписью — например, сколько человек ответили. */
  note?: string;
};

/** Столбики без библиотеки графиков.
 *
 * Данных здесь мало — недели семестра, — и ради них тянуть чарт-библиотеку
 * в приложение, которое грузится по мобильной сети, было бы расточительно.
 */
export function Bars({
  data,
  hint,
  color = "var(--link)",
  compact = false,
  max,
  format,
}: {
  data: Bar[];
  hint?: string;
  /** Цвет основного ряда: у динамики интереса он совпадает с цветом отметки. */
  color?: string;
  /** В половину ширины экрана: столбики и подписи мельче, но подписи остаются
   *  у каждого — без них половинки приходится отсчитывать глазами. */
  compact?: boolean;
  /** Верх шкалы. Без него — самый высокий столбик: для счётчиков это честно,
   *  а у оценок шкала своя, и 3,9 из 5 не должно выглядеть полным столбиком. */
  max?: number;
  /** Подпись значения над столбиком. Без неё — только высота. */
  format?(value: number): string;
}) {
  const peak =
    max ?? Math.max(1, ...data.map((point) => (point.value ?? 0) + (point.extra ?? 0)));

  return (
    <>
      <div className={`bars ${compact ? "bars--compact" : ""} ${format ? "bars--valued" : ""}`}>
        {data.map((point) => (
          <div
            className="bars__item"
            key={point.label}
            title={`${point.label}: ${point.value ?? "—"}${point.note ? ` · ${point.note}` : ""}`}
          >
            {format && (
              <span className="bars__value">
                {point.value === null ? "—" : format(point.value)}
              </span>
            )}
            <div className="bars__stack">
              {point.extra !== undefined && point.extra > 0 && (
                <div
                  className="bars__bar bars__bar--extra"
                  style={{ height: `${(point.extra / peak) * 100}%` }}
                />
              )}
              {point.value !== null && (
                <div
                  className="bars__bar"
                  style={{ height: `${(point.value / peak) * 100}%`, background: color }}
                />
              )}
            </div>
            <span className="bars__label">{point.label}</span>
            {point.note && <span className="bars__note">{point.note}</span>}
          </div>
        ))}
      </div>
      {hint && <p className="hint">{hint}</p>}
    </>
  );
}

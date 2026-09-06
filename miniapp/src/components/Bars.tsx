type Bar = { label: string; value: number; extra?: number };

/** Столбики без библиотеки графиков.
 *
 * Данных здесь мало — недели семестра, — и ради них тянуть чарт-библиотеку
 * в приложение, которое грузится по мобильной сети, было бы расточительно.
 */
export function Bars({ data, hint }: { data: Bar[]; hint?: string }) {
  const peak = Math.max(1, ...data.map((point) => point.value + (point.extra ?? 0)));

  return (
    <>
      <div className="bars">
        {data.map((point) => (
          <div className="bars__item" key={point.label} title={`${point.label}: ${point.value}`}>
            <div className="bars__stack">
              {point.extra !== undefined && point.extra > 0 && (
                <div
                  className="bars__bar bars__bar--extra"
                  style={{ height: `${(point.extra / peak) * 100}%` }}
                />
              )}
              <div
                className="bars__bar"
                style={{ height: `${(point.value / peak) * 100}%` }}
              />
            </div>
            <span className="bars__label">{point.label}</span>
          </div>
        ))}
      </div>
      {hint && <p className="hint">{hint}</p>}
    </>
  );
}

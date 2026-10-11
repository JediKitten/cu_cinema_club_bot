import { useState } from "react";
import { ApiError, setWatched } from "../api";
import { haptic, showMessage } from "../telegram";
import type { FilmBrief, InterestKind } from "../types";

/** «Просмотрено» — в углу карточки, отдельно от кнопок состояния.
 *
 * Оно не входит в тройку «ничего / Желаемое / Ближайшее» и ничему из неё не
 * мешает: посмотренный фильм можно оставить в желаемом, чтобы сходить снова.
 * Поэтому и место у неё своё, а не в общем ряду.
 */
export function WatchedButton({
  film,
  onChange,
}: {
  film: FilmBrief;
  onChange(kinds: InterestKind[], film: FilmBrief): void;
}) {
  const [busy, setBusy] = useState(false);

  // Фильм из TMDB отмечать можно: в каталог он попадёт в этот же момент.
  // Не за что зацепиться только у карточки совсем без идентификаторов.
  if (film.id === null && film.tmdb_id === null) return null;

  async function toggle(event: React.MouseEvent) {
    // Кнопка лежит внутри кликабельной строки каталога.
    event.stopPropagation();
    if (busy) return;
    setBusy(true);
    haptic();
    try {
      const state = await setWatched(film, !film.watched);
      onChange(state.kinds, state.film);
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      className={`watched-tag ${film.watched ? "is-on" : ""}`}
      disabled={busy}
      onClick={toggle}
      title={film.watched ? "Отмечено как просмотренное" : "Отметить просмотренным"}
    >
      {film.watched ? "✓ Смотрел" : "Смотрел"}
    </button>
  );
}

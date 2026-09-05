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

  // У фильма, найденного в TMDB, ещё нет id — отмечать нечего.
  if (film.id === null) return null;

  async function toggle(event: React.MouseEvent) {
    // Кнопка лежит внутри кликабельной строки каталога.
    event.stopPropagation();
    if (busy) return;
    setBusy(true);
    haptic();
    try {
      const state = await setWatched(film.id!, !film.watched);
      onChange(state.kinds, state.film);
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      className={`watched-dot ${film.watched ? "is-on" : ""}`}
      disabled={busy}
      onClick={toggle}
      title={film.watched ? "Отмечено как просмотренное" : "Отметить просмотренным"}
      aria-label={film.watched ? "Просмотрено" : "Отметить просмотренным"}
    >
      <Eye crossed={!film.watched} />
    </button>
  );
}

function Eye({ crossed }: { crossed: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" aria-hidden="true">
      <path
        d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2.6" stroke="currentColor" strokeWidth="1.8" />
      {/* Перечёркнутый глаз — «ещё не смотрел»: так состояние читается без подписи. */}
      {crossed && (
        <path d="M4 20 20 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      )}
    </svg>
  );
}

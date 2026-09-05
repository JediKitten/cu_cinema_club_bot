import { useState } from "react";
import { ApiError, addInterest, removeInterest, setWatched } from "../api";
import { haptic, webApp } from "../telegram";
import { markButtons } from "../marks";
import type { FilmBrief, InterestKind } from "../types";

type Props = {
  film: FilmBrief;
  /** Не больше одного элемента: состояния взаимоисключающие. */
  kinds: InterestKind[];
  /** Возвращает актуальный фильм: у фильма из TMDB после первой отметки появляется id. */
  onChange(kinds: InterestKind[], film: FilmBrief): void;
  full?: boolean;
};

const LABEL: Record<InterestKind, string> = {
  wishlist: "Хочу посмотреть",
  soon: "Готов в ближайшие 2 недели",
};

const SHORT: Record<InterestKind, string> = {
  wishlist: "Желаемое",
  soon: "Ближайшее",
};

/** Кнопки состояния фильма (§4, уточнение клуба).
 *
 * Состояний три и они взаимоисключающие, поэтому показываем не «обе кнопки
 * всегда», а те, что имеют смысл сейчас:
 *   ничего      → обе кнопки;
 *   «Желаемое»  → только оно (нажать — снять);
 *   «Ближайшее» → только оно (нажать — снять);
 *   срок вышел  → «Желаемое» (чем отметка стала) и предложение продлить.
 *
 * «Просмотрено» стоит особняком: оно не отменяет желания сходить снова.
 */
export function MarkButtons({ film, kinds, onChange, full = false }: Props) {
  const [busy, setBusy] = useState(false);
  const current = kinds[0] ?? null;
  const canRenew = film.can_renew_soon;

  async function run(action: () => Promise<{ kinds: InterestKind[]; film: FilmBrief }>) {
    if (busy) return;
    setBusy(true);
    haptic();
    try {
      const state = await action();
      onChange(state.kinds, state.film);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Не удалось сохранить";
      webApp()?.showAlert(message) ?? alert(message);
    } finally {
      setBusy(false);
    }
  }

  function press(kind: InterestKind, event: React.MouseEvent) {
    // Кнопки живут внутри кликабельной строки каталога — иначе отметка
    // одновременно открывала бы карточку.
    event.stopPropagation();
    // Нажатие на активную кнопку снимает отметку. Исключение — просроченное
    // «Ближайшее»: там та же кнопка означает «продлить».
    const isActive = current === kind && !(kind === "soon" && canRenew);
    void run(() => (isActive ? removeInterest(film.id!) : addInterest(film, kind)));
  }

  function pressWatched(event: React.MouseEvent) {
    event.stopPropagation();
    void run(() => setWatched(film.id!, !film.watched));
  }

  return (
    <div className="marks">
      {markButtons(current, canRenew).map(({ kind, active, renew }) => (
        <button
          key={kind}
          className={`mark mark--${kind} ${active ? "is-on" : ""}`}
          disabled={busy}
          onClick={(event) => press(kind, event)}
        >
          {active ? "✓ " : ""}
          {renew ? "Снова в ближайшее" : full ? LABEL[kind] : SHORT[kind]}
        </button>
      ))}

      {/* Только для фильмов из каталога: у найденного в TMDB ещё нет id. */}
      {film.id !== null && (
        <button
          className={`mark mark--watched ${film.watched ? "is-on" : ""}`}
          disabled={busy}
          onClick={pressWatched}
          title="Не влияет на отметки: посмотренное можно оставить в желаемом"
        >
          {film.watched ? "✓ " : ""}Просмотрено
        </button>
      )}
    </div>
  );
}

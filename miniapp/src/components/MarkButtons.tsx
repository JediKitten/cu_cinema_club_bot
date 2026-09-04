import { useState } from "react";
import { ApiError, addInterest, removeInterest } from "../api";
import { haptic, webApp } from "../telegram";
import type { FilmBrief, InterestKind } from "../types";

type Props = {
  film: FilmBrief;
  kinds: InterestKind[];
  /** Возвращает актуальный фильм: у фильма из TMDB после первой отметки появляется id. */
  onChange(kinds: InterestKind[], film: FilmBrief): void;
};

const LABEL: Record<InterestKind, string> = {
  wishlist: "Хочу посмотреть",
  soon: "Готов в ближайшие 2 недели",
};

const SHORT: Record<InterestKind, string> = {
  wishlist: "Желаемое",
  soon: "Ближайшее",
};

export function MarkButtons({ film, kinds, onChange, full = false }: Props & { full?: boolean }) {
  const [busy, setBusy] = useState<InterestKind | null>(null);

  async function toggle(kind: InterestKind, event: React.MouseEvent) {
    // Кнопки живут внутри кликабельной строки каталога — иначе отметка
    // одновременно открывала бы карточку.
    event.stopPropagation();
    if (busy) return;
    setBusy(kind);
    haptic();
    try {
      const state = kinds.includes(kind)
        ? await removeInterest(film.id!, kind)
        : await addInterest(film, kind);
      onChange(state.kinds, state.film);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Не удалось сохранить отметку";
      webApp()?.showAlert(message) ?? alert(message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="marks">
      {(["wishlist", "soon"] as const).map((kind) => (
        <button
          key={kind}
          className={`mark mark--${kind} ${kinds.includes(kind) ? "is-on" : ""}`}
          disabled={busy !== null}
          onClick={(event) => toggle(kind, event)}
        >
          {kinds.includes(kind) ? "✓ " : ""}
          {full ? LABEL[kind] : SHORT[kind]}
        </button>
      ))}
    </div>
  );
}

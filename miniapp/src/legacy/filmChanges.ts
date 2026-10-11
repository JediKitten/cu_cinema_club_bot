import { useEffect, useRef } from "react";
import type { FilmBrief, InterestKind } from "./types";

type Handler = (kinds: InterestKind[], film: FilmBrief) => void;

const handlers = new Set<Handler>();

/** Карточка фильма открывается поверх списка, и отметки меняют в ней.
 *
 * Список под ней жив и должен узнать об изменении — иначе снятый фильм
 * остаётся в «Моих» до перезахода. Перезагружать список целиком нельзя:
 * это потеряло бы подгруженные страницы и место прокрутки, поэтому карточка
 * рассказывает об изменении, а списки правят у себя одну строку.
 */
export function publishFilmChange(kinds: InterestKind[], film: FilmBrief): void {
  for (const handler of handlers) handler(kinds, film);
}

export function useFilmChanges(handler: Handler): void {
  const latest = useRef(handler);
  latest.current = handler;

  useEffect(() => {
    const wrapped: Handler = (kinds, film) => latest.current(kinds, film);
    handlers.add(wrapped);
    return () => {
      handlers.delete(wrapped);
    };
  }, []);
}

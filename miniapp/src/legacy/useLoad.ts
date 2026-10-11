import { useCallback, useEffect, useState, type DependencyList } from "react";
import { ApiError } from "./api";

// Загрузка данных экрана. Одна и та же пара «загружается / ошибка» была
// написана руками в двух десятках экранов — и в каждом по-своему: где-то
// без защиты от ответа, пришедшего после ухода с экрана, где-то с «Failed to
// fetch» прямо в интерфейсе.

type State<T> = {
  data: T | null;
  error: string | null;
  // Для каких параметров пришёл последний ответ. «Загружается» не хранится,
  // а выводится: ответ есть, но не для текущих параметров. Так эффект не
  // вызывает setState синхронно — лишнего рендера на каждую загрузку нет.
  for: readonly unknown[] | null;
};

function same(a: readonly unknown[] | null, b: readonly unknown[]): boolean {
  return a !== null && a.length === b.length && a.every((item, i) => Object.is(item, b[i]));
}

/** Текст ошибки для человека. Показываем только то, что сказал сервер или
 *  слой запросов, — внутренняя ошибка кода на английском в интерфейс не идёт. */
export function errorText(error: unknown, fallback = "Не удалось загрузить"): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

export type Loaded<T> = {
  data: T | null;
  /** Первая загрузка или перезагрузка по новым параметрам ещё идёт. */
  loading: boolean;
  error: string | null;
  /** Поправить данные на месте — после действия, не дожидаясь перезагрузки. */
  setData(update: T | ((current: T | null) => T | null)): void;
  /** Загрузить заново с теми же параметрами. */
  reload(): void;
};

/**
 * `load` зовётся при монтировании и при каждой смене `deps`. Ответ,
 * пришедший для устаревших параметров или после ухода с экрана, выбрасывается.
 * Прежние данные на время перезагрузки остаются — экран не мигает пустотой.
 */
export function useLoad<T>(load: () => Promise<T>, deps: DependencyList): Loaded<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, for: null });
  const [attempt, setAttempt] = useState(0);
  const key = [...deps, attempt];

  useEffect(() => {
    let alive = true;
    load().then(
      (data) => alive && setState({ data, error: null, for: key }),
      (error) => alive && setState((current) => ({ ...current, error: errorText(error), for: key })),
    );
    return () => {
      alive = false;
    };
    // Зависимости — ровно параметры загрузки: `load` новая на каждый рендер.
  }, key);

  const setData = useCallback((update: T | ((current: T | null) => T | null)) => {
    setState((current) => ({
      ...current,
      data:
        typeof update === "function"
          ? (update as (current: T | null) => T | null)(current.data)
          : update,
    }));
  }, []);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return {
    data: state.data,
    loading: !same(state.for, key),
    error: same(state.for, key) ? state.error : null,
    setData,
    reload,
  };
}

/**
 * Поиск по мере ввода: запрос уходит, когда человек перестал печатать,
 * и только от двух символов. Пока ответ на новый запрос не пришёл, на
 * экране остаются прежние результаты — список не мигает на каждой букве.
 */
export function useSearch<T>(
  query: string,
  search: (query: string) => Promise<T[]>,
  { delay = 300, enabled = true }: { delay?: number; enabled?: boolean } = {},
): { found: T[]; setFound(update: (current: T[]) => T[]): void } {
  const trimmed = query.trim();
  const active = enabled && trimmed.length >= 2;
  const [found, setItems] = useState<T[]>([]);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      search(trimmed).then(
        (items) => alive && setItems(items),
        () => alive && setItems([]),
      );
    }, delay);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
    // `search` новая на каждый рендер; искать заново надо только по запросу.
  }, [trimmed, active, delay]);

  const setFound = useCallback((update: (current: T[]) => T[]) => setItems(update), []);
  // Поле очистили — старые результаты не показываем, даже если они в памяти.
  return { found: active ? found : [], setFound };
}

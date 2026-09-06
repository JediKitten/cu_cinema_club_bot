import { useState, type ReactNode } from "react";

type Props = {
  title: string;
  /** Число рядом с заголовком: свёрнутый список должен говорить, сколько в нём. */
  count?: number;
  hint?: string;
  defaultOpen?: boolean;
  /** Ключ памяти состояния. Без него сворачивание забывается при каждом заходе. */
  storageKey?: string;
  children: ReactNode;
};

function remembered(key: string | undefined, fallback: boolean): boolean {
  if (!key) return fallback;
  try {
    const saved = localStorage.getItem(`section:${key}`);
    return saved === null ? fallback : saved === "1";
  } catch {
    // Приватный режим или запрет на хранилище — не повод ломать экран.
    return fallback;
  }
}

/** Сворачиваемый раздел списка.
 *
 * Списки фильмов длинные, и чтобы добраться до того, что ниже, приходилось
 * прокручивать их целиком. Состояние запоминается: свернувший «Просмотренные»
 * не хочет сворачивать их заново при каждом заходе.
 */
export function Section({ title, count, hint, defaultOpen = true, storageKey, children }: Props) {
  const [open, setOpen] = useState(() => remembered(storageKey, defaultOpen));

  function toggle() {
    const next = !open;
    setOpen(next);
    if (storageKey) {
      try {
        localStorage.setItem(`section:${storageKey}`, next ? "1" : "0");
      } catch {
        /* не сохранилось — переживём */
      }
    }
  }

  return (
    <section className="section">
      <button className="section__head" onClick={toggle} aria-expanded={open}>
        <span className="section__title">
          {title}
          {count !== undefined && <span className="hint"> · {count}</span>}
        </span>
        <span className={`section__chevron ${open ? "is-open" : ""}`} aria-hidden>
          ▾
        </span>
      </button>
      {open && (
        <>
          {hint && <p className="hint section__hint">{hint}</p>}
          {children}
        </>
      )}
    </section>
  );
}

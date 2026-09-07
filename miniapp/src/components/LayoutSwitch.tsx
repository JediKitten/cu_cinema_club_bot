export type Layout = "list" | "grid";

const KEY = "catalog-layout";

/** Как человек оставил каталог в прошлый раз. Переключатель, который каждый
 *  раз забывает выбор, приходится нажимать заново — и он раздражает. */
export function rememberedLayout(): Layout {
  try {
    return localStorage.getItem(KEY) === "grid" ? "grid" : "list";
  } catch {
    return "list";
  }
}

export function rememberLayout(layout: Layout): void {
  try {
    localStorage.setItem(KEY, layout);
  } catch {
    /* хранилище недоступно — переживём */
  }
}

function ListIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="1" y="2" width="4" height="4" rx="1" fill="currentColor" />
      <rect x="1" y="10" width="4" height="4" rx="1" fill="currentColor" />
      <rect x="7" y="3" width="8" height="2" rx="1" fill="currentColor" />
      <rect x="7" y="11" width="8" height="2" rx="1" fill="currentColor" />
    </svg>
  );
}

function GridIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      {[1, 6, 11].map((y) =>
        [1, 6, 11].map((x) => (
          <rect key={`${x}-${y}`} x={x} y={y} width="4" height="4" rx="1" fill="currentColor" />
        )),
      )}
    </svg>
  );
}

export function LayoutSwitch({
  layout,
  onChange,
}: {
  layout: Layout;
  onChange(next: Layout): void;
}) {
  return (
    <div className="layout-switch">
      <button
        className={`mark ${layout === "list" ? "is-on mark--wishlist" : ""}`}
        onClick={() => onChange("list")}
        title="Списком"
        aria-label="Списком"
      >
        <ListIcon />
      </button>
      <button
        className={`mark ${layout === "grid" ? "is-on mark--wishlist" : ""}`}
        onClick={() => onChange("grid")}
        title="Плиткой"
        aria-label="Плиткой"
      >
        <GridIcon />
      </button>
    </div>
  );
}

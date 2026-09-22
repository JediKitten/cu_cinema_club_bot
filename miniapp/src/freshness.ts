// Сверка своей сборки с сервером.
//
// Telegram держит Mini App в кэше подолгу и о выкатах не знает. Однажды это
// заперло людей снаружи: сервер уже не присылал поле, которое ждала старая
// сборка, и она показывала экран, из которого не было выхода. Теперь сборка
// знает свой коммит, сервер отдаёт свой в /health, и при расхождении
// приложение перезагружается само.

const BUILT: string = import.meta.env.VITE_APP_VERSION || "dev";
const BASE = import.meta.env.VITE_API_URL ?? "";

// Уходил из приложения ненадолго — скорее всего, скопировать текст или
// ответить в чат. Перезагрузка в этот момент стёрла бы недописанное, поэтому
// после короткой отлучки не перезагружаемся, а ждём следующего раза.
const AWAY_BEFORE_RELOAD_MS = 5 * 60_000;

// Под какую версию сервера уже перезагружались в этой вкладке. Если сервер
// и сборка почему-то так и не сошлись, второй перезагрузки не будет —
// бесконечный цикл хуже устаревшего экрана.
const RELOADED_FOR = "cinema:reloaded-for";

export function isOutdated(server: string | undefined, built: string = BUILT): boolean {
  if (!server || server === "dev" || built === "dev") return false;
  return server !== built;
}

async function serverVersion(): Promise<string | undefined> {
  try {
    const response = await fetch(`${BASE}/health`, { cache: "no-store" });
    if (!response.ok) return undefined;
    const body = (await response.json()) as { version?: string };
    return body.version;
  } catch {
    // Нет сети — не повод что-то делать: проверим в следующий раз.
    return undefined;
  }
}

function alreadyReloadedFor(version: string): boolean {
  try {
    return sessionStorage.getItem(RELOADED_FOR) === version;
  } catch {
    return false;
  }
}

async function reloadIfOutdated(): Promise<void> {
  const version = await serverVersion();
  if (!version || !isOutdated(version) || alreadyReloadedFor(version)) return;
  try {
    sessionStorage.setItem(RELOADED_FOR, version);
  } catch {
    // Без хранилища не узнаем, что уже перезагружались, — и не рискуем.
    return;
  }
  location.reload();
}

export function watchForUpdates(): void {
  if (BUILT === "dev") return;
  void reloadIfOutdated();

  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      hiddenAt = Date.now();
    } else if (hiddenAt && Date.now() - hiddenAt >= AWAY_BEFORE_RELOAD_MS) {
      void reloadIfOutdated();
    }
  });
}

/** Обёртка над Telegram WebApp SDK.
 *
 * SDK приходит скриптом с telegram.org, типов в пакете нет — описываем только то,
 * чем реально пользуемся. За пределами Telegram объекта нет вовсе, поэтому каждое
 * обращение допускает его отсутствие: приложение должно открываться и в обычном
 * браузере, иначе его невозможно отлаживать.
 */

type BackButton = {
  show(): void;
  hide(): void;
  onClick(cb: () => void): void;
  offClick(cb: () => void): void;
};

type HapticFeedback = {
  impactOccurred(style: "light" | "medium" | "heavy"): void;
  notificationOccurred(type: "error" | "success" | "warning"): void;
};

type WebApp = {
  initData: string;
  colorScheme: "light" | "dark";
  /** «unknown» вне Telegram: сам SDK грузится с telegram.org и в обычном
   *  браузере, поэтому наличие объекта ничего не доказывает. */
  platform?: string;
  BackButton: BackButton;
  HapticFeedback: HapticFeedback;
  version?: string;
  isVersionAtLeast?(version: string): boolean;
  ready(): void;
  expand(): void;
  showConfirm?(message: string, callback: (ok: boolean) => void): void;
  setHeaderColor?(color: string): void;
  setBackgroundColor?(color: string): void;
  showAlert(message: string): void;
  openTelegramLink?(url: string): void;
  openLink?(url: string): void;
  downloadFile?(params: { url: string; file_name: string }, callback?: (ok: boolean) => void): void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
  }
}

export const webApp = (): WebApp | undefined => window.Telegram?.WebApp;

// Тот же цвет, что и --bg в index.css. Дублируется намеренно: шапку и фон
// вокруг окна красит сам Telegram, до CSS приложения он не добирается.
const BACKGROUND = "#0f1012";

export function initTelegram(): void {
  const app = webApp();
  app?.ready();
  app?.expand();
  // Методы появились в Bot API 6.9: в старых клиентах их просто нет, и это
  // не повод падать — тогда шапка останется в теме мессенджера.
  try {
    app?.setHeaderColor?.(BACKGROUND);
    app?.setBackgroundColor?.(BACKGROUND);
  } catch {
    /* клиент старее нужного — переживём */
  }
}

export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  webApp()?.HapticFeedback?.impactOccurred(style);
}

export function getInitData(): string {
  const real = webApp()?.initData;
  if (real) return real;

  // Отладка вне Telegram: ?initData=<подписанная строка>. Это не обход входа —
  // подпись всё равно проверяется бэкендом по токену бота, здесь лишь способ
  // передать её без мессенджера. В прод-сборку ветка не попадает.
  if (import.meta.env.DEV) {
    return new URLSearchParams(location.search).get("initData") ?? "";
  }
  return "";
}

/** Есть ли у клиента своя кнопка «назад».
 *
 * Проверять наличие объекта бесполезно: SDK грузится скриптом с telegram.org
 * и в обычном браузере, где `BackButton` существует, но ничего не рисует —
 * а окно карточки закрывает экран целиком вместе с панелью вкладок, и выйти
 * из него было бы нечем. Отличает настоящий Telegram `platform`: вне его
 * SDK честно отвечает «unknown».
 */
export function hasBackButton(): boolean {
  const app = webApp();
  return Boolean(app?.BackButton) && Boolean(app?.platform) && app?.platform !== "unknown";
}

/** Кнопка «назад» рисуется самим Telegram, а не нами — поэтому подписка живёт здесь.
 *
 * Не хук, хотя и зовётся из эффекта: возвращает отписку, которую эффект и
 * отдаёт React. Имя с `use` линтер справедливо принимал за хук в колбэке.
 */
export function bindBackButton(visible: boolean, onBack: () => void): () => void {
  const button = webApp()?.BackButton;
  if (!button) return () => {};
  if (visible) {
    button.onClick(onBack);
    button.show();
  } else {
    button.hide();
  }
  return () => {
    button.offClick(onBack);
    button.hide();
  };
}

/** Умеет ли клиент показывать окна сам.
 *
 * Метод в SDK есть всегда, но вне Telegram и в клиентах старее Bot API 6.2 он
 * молча ничего не делает — а `showConfirm` при этом никогда не зовёт колбэк,
 * и обещание, которого ждёт вызывающий, не разрешается никогда.
 */
function supportsPopups(): boolean {
  const app = webApp();
  return Boolean(app?.showAlert && app.isVersionAtLeast?.("6.2"));
}

/** Показать сообщение пользователю.
 *
 * Раньше здесь было `webApp()?.showAlert(m) ?? alert(m)`, и это давало два окна
 * подряд: showAlert ничего не возвращает, поэтому `??` срабатывал всегда.
 */
export function showMessage(message: string): void {
  if (supportsPopups()) {
    webApp()!.showAlert!(message);
  } else {
    alert(message);
  }
}

/** Спросить «точно?» и дождаться ответа.
 *
 * В Telegram это родное окно, вне его — браузерное confirm. Возвращаем
 * промис: вызывающему нужен ответ, а не колбэк посреди обработчика.
 */
export function askConfirm(message: string): Promise<boolean> {
  const app = webApp();
  if (supportsPopups() && app?.showConfirm) {
    return new Promise((resolve) => app.showConfirm!(message, resolve));
  }
  return Promise.resolve(window.confirm(message));
}

/** Переслать ссылку через Telegram.
 *
 * Отправляем только адрес, без приписанного текста: сообщение с текстом
 * выглядело как пересылка чужого поста, а нужно просто дать ссылку.
 * Обычный window.open из webview не работает — нужен openTelegramLink.
 */
export function shareLink(url: string): boolean {
  const app = webApp();
  if (!app?.openTelegramLink) return false;
  app.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(url)}`);
  return true;
}

/** Отдать файл человеку — например, показ в календарь.
 *
 * В Telegram ссылка на файл из Mini App никуда не ведёт: webview не умеет
 * скачивать. С Bot API 8.0 есть downloadFile — Telegram сам спросит, сохранить
 * ли файл, и откроет его штатным приложением (для .ics — календарём). В старых
 * клиентах отдаём адрес браузеру телефона: он предложит добавить событие сам.
 */
export function downloadFile(url: string, fileName: string): void {
  const app = webApp();
  if (app?.downloadFile && app.isVersionAtLeast?.("8.0")) {
    app.downloadFile({ url, file_name: fileName });
  } else if (app?.openLink && app.platform !== "unknown") {
    app.openLink(url);
  } else {
    window.location.href = url;
  }
}

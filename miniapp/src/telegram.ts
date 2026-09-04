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
  BackButton: BackButton;
  HapticFeedback: HapticFeedback;
  ready(): void;
  expand(): void;
  showAlert(message: string): void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
  }
}

export const webApp = (): WebApp | undefined => window.Telegram?.WebApp;

export function initTelegram(): void {
  const app = webApp();
  app?.ready();
  app?.expand();
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

/** Кнопка «назад» рисуется самим Telegram, а не нами — поэтому подписка живёт здесь. */
export function useTelegramBackButton(visible: boolean, onBack: () => void): () => void {
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

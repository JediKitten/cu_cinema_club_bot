import { hasBackButton } from "../telegram";

/** Своя кнопка «назад» — на случай, когда родной у клиента нет.
 *
 * В Telegram её рисует сам мессенджер, и дублировать не нужно. В браузере
 * (а также в клиентах старее Bot API 6.2) окно поверх вкладки закрывало бы
 * экран без единого выхода.
 */
export function BackLink({ onBack, label = "← Назад" }: { onBack(): void; label?: string }) {
  if (hasBackButton()) return null;
  return (
    <button className="mark back-link" onClick={onBack}>
      {label}
    </button>
  );
}

import { useState } from "react";
import { ApiError, getInvite } from "../api";
import { haptic, shareLink, showMessage } from "../telegram";
import type { FilmCard } from "../types";

/** Позвать друзей на конкретный фильм.
 *
 * Ссылка ведёт в бота, тот показывает карточку и кнопку. Голос по ней не
 * ставится: приглашённый решает сам, одним нажатием.
 *
 * Показываем саму ссылку, а не прячем за окном пересылки: её чаще хотят просто
 * скопировать и бросить в свой чат, чем отправлять через телеграмный диалог.
 */
export function InviteButton({ film }: { film: FilmCard }) {
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState<{
    link: string;
    invited: number;
    accepted: number;
  } | null>(null);
  const [copied, setCopied] = useState(false);

  // У фильма из TMDB ещё нет id — звать не на что.
  if (film.id === null) return null;

  async function load() {
    if (busy || invite) return;
    setBusy(true);
    haptic();
    try {
      const data = await getInvite(film.id!);
      setInvite({ link: data.link, invited: data.invited, accepted: data.accepted });
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не удалось создать ссылку");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!invite) return;
    haptic();
    try {
      await navigator.clipboard.writeText(invite.link);
      setCopied(true);
      // Возвращаем подпись: иначе кнопка навсегда остаётся «Скопировано»
      // и непонятно, сработало ли повторное нажатие.
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Буфер недоступен — ссылка на экране, её можно выделить руками.
      showMessage("Скопируйте ссылку вручную");
    }
  }

  if (!invite) {
    return (
      <button className="mark" disabled={busy} onClick={load}>
        🔗 Позвать друзей
      </button>
    );
  }

  return (
    <div className="invite">
      <p className="hint">
        Ссылка зовёт именно на этот фильм. Голос за друга она не ставит — он решит сам.
      </p>

      {/* Только чтение, но выделяемо: если буфер обмена недоступен, ссылку
          всё равно можно скопировать руками. */}
      <input className="field invite__link" value={invite.link} readOnly onFocus={(e) => e.target.select()} />

      <div className="marks">
        <button className={`mark ${copied ? "mark--going is-on" : ""}`} onClick={copy}>
          {copied ? "✓ Скопировано" : "Скопировать"}
        </button>
        <button
          className="mark"
          onClick={() => {
            haptic();
            // Пересылка — только сама ссылка, без приписанного текста.
            if (!shareLink(invite.link)) showMessage("Переслать можно из Telegram");
          }}
        >
          Переслать
        </button>
      </div>

      {invite.invited > 0 && (
        <p className="hint">
          По вашим ссылкам пришли {invite.invited}, отметили фильм {invite.accepted}.
        </p>
      )}
    </div>
  );
}

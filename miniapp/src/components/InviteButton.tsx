import { useState } from "react";
import { ApiError, getInvite } from "../api";
import { haptic, shareLink, showMessage } from "../telegram";
import type { FilmCard } from "../types";

/** Позвать друзей на конкретный фильм.
 *
 * Ссылка ведёт в бота, тот показывает карточку и кнопку. Голос по ней не
 * ставится: приглашённый решает сам, одним нажатием. Иначе накрутить вес
 * фильма было бы вопросом рассылки ссылки в чат.
 */
export function InviteButton({ film }: { film: FilmCard }) {
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState<{ invited: number; accepted: number } | null>(null);

  // У фильма из TMDB ещё нет id — звать не на что.
  if (film.id === null) return null;

  async function invite() {
    if (busy) return;
    setBusy(true);
    haptic();
    try {
      const data = await getInvite(film.id!);
      setStats({ invited: data.invited, accepted: data.accepted });

      const text = `Зову на «${film.title_ru}» в киноклубе`;
      if (!shareLink(data.link, text)) {
        // Вне Telegram делимся через буфер обмена.
        await navigator.clipboard?.writeText(data.link);
        showMessage("Ссылка скопирована");
      }
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не удалось создать ссылку");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="mark" disabled={busy} onClick={invite}>
        🔗 Позвать друзей
      </button>
      {stats && stats.invited > 0 && (
        <p className="hint">
          По вашим ссылкам пришли {stats.invited}, отметили фильм {stats.accepted}.
        </p>
      )}
    </>
  );
}

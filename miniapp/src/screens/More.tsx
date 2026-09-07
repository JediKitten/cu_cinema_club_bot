import { useEffect, useState } from "react";
import { createFilmRequest, myFilmRequests } from "../api";
import { haptic } from "../telegram";
import type { FilmRequest, User } from "../types";
import { ROLE_LABEL } from "../roles";
import { Admin } from "./Admin";
import { Avatar } from "./Profile";
import { History } from "./History";

const STATUS: Record<FilmRequest["status"], string> = {
  pending: "на модерации",
  approved: "добавлен",
  rejected: "отклонён",
};

// Кнопка «Клуб» видна только тем, кому есть что там делать. Это удобство,
// а не защита: права проверяет бэкенд на каждом запросе.
const ADMIN_ROLES = new Set(["moderator", "admin", "superadmin"]);

type Props = {
  user: User;
  onOpenProfile(userId: number): void;
};

export function More({ user, onOpenProfile }: Props) {
  const [showHistory, setShowHistory] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [note, setNote] = useState("");
  const [requests, setRequests] = useState<FilmRequest[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    myFilmRequests().then(setRequests).catch(() => {});
  }, []);

  async function submit() {
    if (!title.trim() || sending) return;
    setSending(true);
    setError(null);
    try {
      const created = await createFilmRequest({
        raw_title: title.trim(),
        raw_year: year.trim() ? Number(year) : null,
        note: note.trim() || null,
      });
      setRequests((current) => [created, ...current]);
      setTitle("");
      setYear("");
      setNote("");
      haptic("medium");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось отправить заявку");
    } finally {
      setSending(false);
    }
  }

  /** Подраздел «Ещё»: своя кнопка возврата, потому что родная «назад»
   *  Telegram занята карточкой фильма, которая может открыться поверх. */
  function Subscreen({ onClose, children }: { onClose(): void; children: React.ReactNode }) {
    return (
      <>
        <div className="screen" style={{ paddingBottom: 0 }}>
          <button className="mark" style={{ alignSelf: "flex-start" }} onClick={onClose}>
            ← Назад
          </button>
        </div>
        {children}
      </>
    );
  }

  if (showHistory) {
    return (
      <Subscreen onClose={() => setShowHistory(false)}>
        <History />
      </Subscreen>
    );
  }

  if (showAdmin) {
    return (
      <Subscreen onClose={() => setShowAdmin(false)}>
        <Admin me={user} />
      </Subscreen>
    );
  }

  return (
    <div className="screen">
      {/* Своя карточка — вход в профиль: там же живут четыре любимых фильма. */}
      <button className="slot-row person-row" onClick={() => onOpenProfile(user.id)}>
        <span className="person-row__main">
          <Avatar url={user.photo_url} name={user.display_name} size={44} />
          <span>
            <p className="film-row__title">{user.display_name}</p>
            <p className="meta">
              {user.tg_username ? `@${user.tg_username} · ` : ""}
              {ROLE_LABEL[user.role]}
            </p>
          </span>
        </span>
        <span className="hint">мой профиль →</span>
      </button>

      {ADMIN_ROLES.has(user.role) && (
        <button className="primary" onClick={() => setShowAdmin(true)}>
          ⚙ Клуб
        </button>
      )}

      <button className="primary" onClick={() => setShowHistory(true)}>
        🕘 Что уже смотрели
      </button>

      <h2 style={{ fontSize: 16, margin: "8px 0 0" }}>Не нашёл фильм</h2>
      <p className="hint" style={{ marginTop: -6 }}>
        Если фильма нет ни в каталоге, ни в поиске — оставьте заявку, её разберёт
        администратор.
      </p>

      <input
        className="field"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Название"
      />
      <input
        className="field"
        value={year}
        onChange={(event) => setYear(event.target.value.replace(/\D/g, "").slice(0, 4))}
        placeholder="Год (необязательно)"
        inputMode="numeric"
      />
      <input
        className="field"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Ссылка или комментарий (необязательно)"
      />

      {error && <div className="error">{error}</div>}

      <button className="primary" onClick={submit} disabled={!title.trim() || sending}>
        {sending ? "Отправляем…" : "Отправить заявку"}
      </button>

      {requests.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, margin: "8px 0 0" }}>Мои заявки</h2>
          {requests.map((request) => (
            <div className="review" key={request.id}>
              <div className="review__head">
                <span>
                  {request.raw_title}
                  {request.raw_year ? ` (${request.raw_year})` : ""}
                </span>
                <span>{STATUS[request.status]}</span>
              </div>
              {request.resolution_comment}
            </div>
          ))}
        </>
      )}

      <p className="attribution">
        This product uses the TMDB API but is not endorsed or certified by TMDB.
      </p>
    </div>
  );
}

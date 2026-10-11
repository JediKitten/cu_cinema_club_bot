import { lazy, Suspense, useEffect, useState } from "react";
import { createFilmRequest, myFilmRequests } from "../api";
import { haptic } from "../telegram";
import type { FilmRequest, User } from "../types";

// Админка нужна единицам из полутора сотен, а весит заметную долю бандла:
// остальные её не скачивают вовсе.
const Admin = lazy(() => import("./Admin").then((module) => ({ default: module.Admin })));
import { History } from "./History";

const STATUS: Record<FilmRequest["status"], string> = {
  pending: "на модерации",
  approved: "добавлен",
  rejected: "отклонён",
};

// Кнопка «Клуб» видна только тем, кому есть что там делать. Это удобство,
// а не защита: права проверяет бэкенд на каждом запросе.
const ADMIN_ROLES = new Set(["moderator", "admin", "superadmin"]);

/** Подраздел «Ещё»: своя кнопка возврата, потому что родная «назад»
 *  Telegram занята карточкой фильма, которая может открыться поверх.
 *
 *  Объявлен снаружи More нарочно. Внутри он был бы новым компонентом на
 *  каждый рендер, и React пересоздавал бы всё под ним: открыл поверх
 *  админки карточку фильма, закрыл — админка начинается с чистого листа. */
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

export function More({ user }: { user: User }) {
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
        <Suspense fallback={<div className="center">Загрузка…</div>}>
          <Admin me={user} />
        </Suspense>
      </Subscreen>
    );
  }

  return (
    <div className="screen">
      {/* Кто вошёл, здесь не повторяем: на этот экран приходят из профиля,
          где имя и роль только что были на виду. */}
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

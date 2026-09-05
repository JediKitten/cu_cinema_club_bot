import { useEffect, useState } from "react";
import { createFilmRequest, myFilmRequests } from "../api";
import { haptic } from "../telegram";
import type { FilmRequest, User } from "../types";
import { History } from "./History";

const STATUS: Record<FilmRequest["status"], string> = {
  pending: "на модерации",
  approved: "добавлен",
  rejected: "отклонён",
};

export function More({ user }: { user: User }) {
  const [showHistory, setShowHistory] = useState(false);
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
      <>
        <div className="screen" style={{ paddingBottom: 0 }}>
          <button className="mark" style={{ alignSelf: "flex-start" }} onClick={() => setShowHistory(false)}>
            ← Назад
          </button>
        </div>
        <History />
      </>
    );
  }

  return (
    <div className="screen">
      <div>
        <h2 style={{ fontSize: 16, margin: 0 }}>{user.display_name}</h2>
        <p className="meta">
          {user.role === "user" ? "участник клуба" : `роль: ${user.role}`}
        </p>
      </div>

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

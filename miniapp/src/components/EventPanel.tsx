import { useState } from "react";
import { ApiError, createEvent, searchFilms } from "../api";
import { showMessage } from "../telegram";
import type { FilmBrief } from "../types";

/** Событие в обход алгоритма (§10, расширение по просьбе клуба).
 *
 * Фильм необязателен: можно объявить время заранее и раскрыть название позже —
 * ради этого и нужна подпись вроде «ждите анонса».
 */
export function EventPanel({ onCreated }: { onCreated(): void }) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("19:00");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<FilmBrief[]>([]);
  const [film, setFilm] = useState<FilmBrief | null>(null);
  const [busy, setBusy] = useState(false);

  async function lookup() {
    if (query.trim().length < 2) return;
    try {
      setFound((await searchFilms(query.trim())).filter((f) => f.id !== null).slice(0, 5));
    } catch {
      setFound([]);
    }
  }

  async function submit() {
    if (busy || !date) return;
    if (!film && !title.trim()) {
      showMessage("Укажите фильм или заголовок события");
      return;
    }
    setBusy(true);
    try {
      // Время вводится местное; в ISO с зоной браузера его переведёт сам Date.
      const startsAt = new Date(`${date}T${time || "19:00"}:00`).toISOString();
      await createEvent({
        starts_at: startsAt,
        film_id: film?.id ?? null,
        title: title.trim() || null,
        note: note.trim() || null,
      });
      setDate("");
      setTitle("");
      setNote("");
      setFilm(null);
      setQuery("");
      setFound([]);
      showMessage("Событие создано");
      onCreated();
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3>Своё событие</h3>
      <p className="hint">
        Назначается на любое время, минуя алгоритм. Фильм можно не указывать —
        тогда напишите заголовок и подпись.
      </p>

      <div className="setting__pair">
        <input
          className="field"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <input
          className="field"
          type="time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
        />
      </div>

      {film ? (
        <div className="slot-row">
          <div>
            <p className="film-row__title">{film.title_ru}</p>
            <p className="meta">{film.year}</p>
          </div>
          <button className="mark" onClick={() => setFilm(null)}>
            убрать
          </button>
        </div>
      ) : (
        <>
          <input
            className="field"
            value={query}
            placeholder="Найти фильм (необязательно)"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && lookup()}
            onBlur={lookup}
          />
          {found.map((item) => (
            <button
              className="slot-row"
              key={item.id}
              onClick={() => {
                setFilm(item);
                setFound([]);
              }}
            >
              <div>
                <p className="film-row__title">{item.title_ru}</p>
                <p className="meta">{item.year}</p>
              </div>
              <span />
            </button>
          ))}
        </>
      )}

      <input
        className="field"
        value={title}
        placeholder="Заголовок, если без фильма"
        onChange={(e) => setTitle(e.target.value)}
      />
      <input
        className="field"
        value={note}
        placeholder="Подпись, например «ждите анонса»"
        onChange={(e) => setNote(e.target.value)}
      />

      <button className="primary" disabled={busy || !date} onClick={submit}>
        Создать событие
      </button>
    </>
  );
}

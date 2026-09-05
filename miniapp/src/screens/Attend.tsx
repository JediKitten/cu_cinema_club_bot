import { useEffect, useState } from "react";
import { ApiError, attendByCode, getFeedback, saveFeedback } from "../api";
import { Poster } from "../components/FilmRow";
import { haptic } from "../telegram";
import type { FeedbackState, Screening } from "../types";

/** Этап 4 (§8): отметка присутствия кодом с экрана, затем оценка.
 *
 * Обязательна только отметка — форму можно пропустить, о ней потом напомнят.
 */
export function Attend({ screening, onBack }: { screening: Screening; onBack(): void }) {
  const [state, setState] = useState<FeedbackState | null>(null);
  const [code, setCode] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [review, setReview] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getFeedback(screening.id)
      .then((next) => {
        setState(next);
        setRating(next.film_rating);
        setReview(next.review_text ?? "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, [screening.id]);

  async function submitCode() {
    if (busy || code.trim().length < 4) return;
    setBusy(true);
    setError(null);
    haptic("medium");
    try {
      setState(await attendByCode(screening.id, code.trim()));
      setCode("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не получилось отметиться");
    } finally {
      setBusy(false);
    }
  }

  async function submitFeedback() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await saveFeedback(screening.id, {
        film_rating: rating,
        review_text: review.trim() || null,
      });
      setState(next);
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  if (error && !state) return <div className="screen"><div className="error">{error}</div></div>;
  if (!state) return <div className="center">Загрузка…</div>;

  return (
    <div className="screen">
      <button className="mark" style={{ alignSelf: "flex-start" }} onClick={onBack}>
        ← Назад
      </button>

      <div className="film-row">
        <Poster url={state.film.poster_url} />
        <div>
          <p className="film-row__title">{state.film.title_ru}</p>
          <p className="meta">{state.film.year}</p>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {!state.attended ? (
        <>
          <h3>Код с экрана</h3>
          <p className="hint">
            Введите цифры, которые показывают в зале. Код меняется каждую минуту.
          </p>
          <input
            className="field code-input"
            inputMode="numeric"
            autoComplete="off"
            placeholder="000000"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          />
          <button className="primary" disabled={busy || code.length < 4} onClick={submitCode}>
            Отметиться
          </button>
        </>
      ) : (
        <>
          <p className="badge">✓ Присутствие отмечено</p>

          <h3>Как вам фильм?</h3>
          <p className="hint">Необязательно, но помогает собирать рейтинг клуба.</p>

          <div className="rating-row">
            {Array.from({ length: 10 }, (_, i) => i + 1).map((value) => (
              <button
                key={value}
                className={`rating-dot ${rating === value ? "is-on" : ""}`}
                onClick={() => {
                  haptic();
                  // Повторное нажатие снимает оценку: передумать можно.
                  setRating(rating === value ? null : value);
                  setSaved(false);
                }}
              >
                {value}
              </button>
            ))}
          </div>

          <textarea
            className="field"
            rows={4}
            placeholder="Отзыв, если хочется"
            value={review}
            onChange={(e) => {
              setReview(e.target.value);
              setSaved(false);
            }}
          />

          <button className="primary" disabled={busy} onClick={submitFeedback}>
            {saved ? "Сохранено ✓" : "Сохранить"}
          </button>
        </>
      )}
    </div>
  );
}

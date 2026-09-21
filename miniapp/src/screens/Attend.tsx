import { useEffect, useState } from "react";
import { ApiError, attendByCode, getFeedback, saveFeedback } from "../api";
import { Poster } from "../components/FilmRow";
import { StarRating } from "../components/StarRating";
import { haptic } from "../telegram";
import type { DiscussionSkip, FeedbackState } from "../types";

/** Оценки ездят полубаллами (1..10), а показываются звёздами (0,5..5). */
const toStars = (half: number | null) => (half === null ? null : half / 2);
const toHalf = (stars: number | null) => (stars === null ? null : Math.round(stars * 2));

/** Этап 4 (§8): отметка присутствия кодом с экрана, затем опрос.
 *
 * Опрос — тот самый CSAT, которым клуб отчитывается перед вузом. Про это
 * сказано прямо в форме: просьба «отвечайте честно» без объяснения, кому и
 * зачем, читается как вежливая формальность, и в ответ приходят вежливые
 * пятёрки. Обязательна по-прежнему только отметка присутствия.
 */
export function Attend({
  screeningId,
  title,
  onBack,
  backLabel = "← Назад",
}: {
  screeningId: number;
  /** Название на случай события без фильма: у него карточки нет. */
  title?: string;
  onBack(): void;
  /** Подпись возврата. Задаётся там, где над формой уже есть чужая «назад»:
   *  две одинаковые кнопки подряд выглядят как сбой вёрстки. */
  backLabel?: string;
}) {
  const [state, setState] = useState<FeedbackState | null>(null);
  const [code, setCode] = useState("");
  const [visit, setVisit] = useState<number | null>(null);
  const [film, setFilm] = useState<number | null>(null);
  const [discussion, setDiscussion] = useState<number | null>(null);
  const [skip, setSkip] = useState<DiscussionSkip | null>(null);
  const [review, setReview] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getFeedback(screeningId)
      .then((next) => {
        setState(next);
        setVisit(toStars(next.visit_rating));
        setFilm(toStars(next.film_rating));
        setDiscussion(toStars(next.discussion_rating));
        setSkip(next.discussion_skip);
        setReview(next.review_text ?? "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, [screeningId]);

  function touched() {
    setSaved(false);
  }

  async function submitCode() {
    if (busy || code.trim().length < 4) return;
    setBusy(true);
    setError(null);
    haptic("medium");
    try {
      setState(await attendByCode(screeningId, code.trim()));
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
      const next = await saveFeedback(screeningId, {
        visit_rating: toHalf(visit),
        // Вопрос про фильм скрыт — значит, оценка уже есть в каталоге, и
        // пересылать сюда нечего: рейтинг у фильма один.
        film_rating: state?.film_already_rated ? null : toHalf(film),
        discussion_rating: toHalf(discussion),
        discussion_skip: skip,
        review_text: review.trim() || null,
      });
      setState(next);
      setSaved(true);
      haptic("medium");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  if (error && !state) return <div className="screen"><div className="error">{error}</div></div>;
  if (!state) return <div className="center">Загрузка…</div>;

  // Оценку фильма спрашиваем один раз: поставивший её в каталоге не должен
  // объяснять то же самое снова. У события без фильма спрашивать и нечего.
  const askAboutFilm = state.film !== null && !state.film_already_rated;

  return (
    <div className="screen">
      <button className="mark" style={{ alignSelf: "flex-start" }} onClick={onBack}>
        {backLabel}
      </button>

      {/* У события без фильма (встреча клуба) карточки нет — только название. */}
      {state.film ? (
        <div className="film-row">
          <Poster url={state.film.poster_url} />
          <div>
            <p className="film-row__title">{state.film.title_ru}</p>
            <p className="meta">{state.film.year}</p>
          </div>
        </div>
      ) : (
        <h3 style={{ marginBottom: 0 }}>{title ?? "Показ клуба"}</h3>
      )}

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

          {/* Зачем это нужно — прямым текстом. Без объяснения просьба
              отвечать честно читается как вежливая формальность. */}
          <div className="notice">
            Клуб отчитывается перед вузом, и отчёт складывается из ваших ответов,
            а не из наших ощущений. Отвечайте честно: заниженная оценка нам
            полезнее вежливой. Четыре вопроса, полминуты.
          </div>

          <h3 className="survey__question">Насколько вам понравилось посещение в целом?</h3>
          <StarRating
            value={visit}
            busy={busy}
            onChange={(next) => {
              setVisit(next);
              touched();
            }}
          />

          {askAboutFilm && (
            <>
              <h3 className="survey__question">Как бы вы оценили фильм?</h3>
              <p className="hint">Это станет вашей оценкой фильма в клубе.</p>
              <StarRating
                value={film}
                busy={busy}
                onChange={(next) => {
                  setFilm(next);
                  touched();
                }}
              />
            </>
          )}

          <h3 className="survey__question">Как бы вы оценили обсуждение после фильма?</h3>
          <StarRating
            value={discussion}
            busy={busy}
            onChange={(next) => {
              setDiscussion(next);
              // Оценка и «не был» вместе не значат ничего — одно снимает другое.
              if (next !== null) setSkip(null);
              touched();
            }}
          />
          <div className="marks">
            {(
              [
                ["absent", "Не был на обсуждении"],
                ["unsure", "Затрудняюсь ответить"],
              ] as [DiscussionSkip, string][]
            ).map(([value, label]) => (
              <button
                key={value}
                className={`mark ${skip === value ? "is-on mark--wishlist" : ""}`}
                disabled={busy}
                onClick={() => {
                  setSkip(skip === value ? null : value);
                  setDiscussion(null);
                  touched();
                }}
              >
                {label}
              </button>
            ))}
          </div>

          <h3 className="survey__question">Любые предложения или критика?</h3>
          <textarea
            className="field"
            rows={4}
            placeholder="Что стоит исправить или повторить"
            value={review}
            onChange={(e) => {
              setReview(e.target.value);
              touched();
            }}
          />

          <button className="primary" disabled={busy} onClick={submitFeedback}>
            {saved ? "Сохранено ✓" : "Отправить"}
          </button>
          <p className="hint">Ответы можно поправить — форма всегда открыта.</p>
        </>
      )}
    </div>
  );
}

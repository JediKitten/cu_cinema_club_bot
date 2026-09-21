import { useState } from "react";
import { ApiError, confirmScreening, declineScreening } from "../api";
import { Poster } from "../components/FilmRow";
import { dayLabel, timeLabel } from "../dates";
import { useOpenFilm } from "../filmOpener";
import { haptic, showMessage } from "../telegram";
import type { Schedule, Screening } from "../types";
import { Attend } from "./Attend";

/** Сеанс уже начался — значит, пора отмечаться, а не подтверждать.
 *  Точное окно проверяет сервер; здесь только момент показа кнопки. */
function started(screening: Screening): boolean {
  return new Date(screening.slot.starts_at).getTime() <= Date.now();
}

/** Этап 3 (§7): опубликованное расписание и подтверждения. */
export function Screenings({
  schedule,
  onChange,
  onGoToVoting,
}: {
  schedule: Schedule;
  onChange(s: Schedule): void;
  /** Увести на неделю, где идёт выбор фильмов. Есть, только когда он идёт. */
  onGoToVoting?(): void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const [attending, setAttending] = useState<Screening | null>(null);
  const openFilm = useOpenFilm();

  async function toggle(screening: Screening) {
    if (busy !== null) return;
    setBusy(screening.id);
    haptic();

    const going = screening.my_state === "confirmed" || screening.my_state === "waitlist";
    try {
      const result = going
        ? await declineScreening(screening.id)
        : await confirmScreening(screening.id);
      onChange({
        ...schedule,
        screenings: schedule.screenings.map((item) =>
          item.id === screening.id
            ? {
                ...item,
                my_state: result.state,
                my_place_in_queue: result.place_in_queue,
                confirmed: result.confirmed,
                capacity: result.capacity,
              }
            : item,
        ),
      });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Не удалось сохранить";
      showMessage(message);
    } finally {
      setBusy(null);
    }
  }

  if (attending) {
    return <Attend screening={attending} onBack={() => setAttending(null)} />;
  }

  const active = schedule.screenings.filter((s) => s.status !== "cancelled");
  const cancelled = schedule.screenings.filter((s) => s.status === "cancelled");

  return (
    <>
      {active.length === 0 &&
        (onGoToVoting ? (
          // Пустая неделя в выходные — это норма: расписание на неё как раз
          // и собирается голосованием. Молчаливое «показов нет» выглядело бы
          // так, будто клуб закрылся.
          <>
            <p className="hint">
              Показов на этой неделе пока нет — их выбирают прямо сейчас.
              Отметьте фильмы, на которые пошли бы, и вечера, когда свободны:
              расписание соберётся из ответов.
            </p>
            <button className="primary" onClick={onGoToVoting}>
              Выбрать фильмы
            </button>
          </>
        ) : (
          <p className="hint">
            На этой неделе показов нет. Отмечайте фильмы в каталоге — из них
            и собирается список, за который голосуют.
          </p>
        ))}
      {active.length > 0 && <p className="hint">Отметьте, на какие сеансы придёте.</p>}

      {active.map((screening) => {
        const going = screening.my_state === "confirmed";
        const queued = screening.my_state === "waitlist";
        const full = screening.confirmed >= screening.capacity;

        return (
          <div
            className={`film-row ${screening.film.id ? "film-row--clickable" : ""}`}
            key={screening.id}
            onClick={() => screening.film.id && openFilm(screening.film)}
          >
            <Poster url={screening.film.poster_url} />
            <div>
              <p className="film-row__title">{screening.film.title_ru}</p>
              <p className="meta">
                {dayLabel(screening.slot.starts_at)} · {timeLabel(screening.slot.starts_at)} ·{" "}
                {screening.slot.hall_name}
              </p>
              {/* Язык решает, пойдёт человек или нет, не хуже самого фильма:
                  в расписание за этим и заглядывают. Плашка, а не строчка
                  в сером тексте рядом с залом, — иначе её не заметят. */}
              {screening.in_english && (
                <p className="badge badge--english">🇬🇧 На английском, без дубляжа</p>
              )}
              {/* Подпись события без фильма — «ждите анонса»: без неё такой
                  вечер выглядит как пустая строка в расписании. */}
              {screening.note && <p className="meta">{screening.note}</p>}
              <p className="meta">
                Придут: {screening.confirmed} из {screening.capacity}
                {queued && screening.my_place_in_queue !== null && (
                  <> · вы {screening.my_place_in_queue}-й в очереди</>
                )}
              </p>

              {/* Записался, а у показа своя регистрация у вуза — она не
                  заменяется нашим «Приду», и человек про неё забывает.
                  Ту же ссылку присылает бот: приложение могли и закрыть. */}
              {(going || queued) && screening.registration_url && (
                <a
                  className="notice notice--link"
                  href={screening.registration_url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(event) => event.stopPropagation()}
                >
                  Не забудьте зарегистрироваться в @cu_clubs_bot →
                </a>
              )}

              <div className="marks">
                <button
                  className={`mark ${going ? "mark--going is-on" : queued ? "mark--soon is-on" : ""}`}
                  disabled={busy !== null}
                  onClick={(event) => {
                    event.stopPropagation();
                    void toggle(screening);
                  }}
                >
                  {going ? "✓ Приду" : queued ? "В очереди" : full ? "Встать в очередь" : "Приду"}
                </button>
                {started(screening) && (
                  // Окно отметки открыто — предлагаем ввести код с экрана (§8).
                  <button
                    className="mark mark--wishlist is-on"
                    onClick={(event) => {
                      event.stopPropagation();
                      setAttending(screening);
                    }}
                  >
                    Я на месте
                  </button>
                )}
                {(going || queued) && !started(screening) && (
                  <span className="hint" style={{ alignSelf: "center" }}>
                    нажмите ещё раз, чтобы отменить
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {cancelled.length > 0 && (
        <>
          <h3>Отменены</h3>
          {cancelled.map((screening) => (
            <div
              className={`film-row ${screening.film.id ? "film-row--clickable" : ""}`}
              key={screening.id}
              style={{ opacity: 0.65 }}
              onClick={() => screening.film.id && openFilm(screening.film)}
            >
              <Poster url={screening.film.poster_url} />
              <div>
                <p className="film-row__title">{screening.film.title_ru}</p>
                <p className="meta">{dayLabel(screening.slot.starts_at)}</p>
                {screening.cancel_reason && <p className="meta">{screening.cancel_reason}</p>}
              </div>
            </div>
          ))}
        </>
      )}
    </>
  );
}

import { useEffect, useState } from "react";
import {
  ApiError,
  cancelEvent,
  createEvent,
  getRound,
  listEvents,
  moveScreening,
  searchFilms,
  updateEvent,
} from "../api";
import { askConfirm, showMessage } from "../telegram";
import { Section } from "./Section";
import type { ClubEvent, EventChanges, FilmBrief, Slot } from "../types";

type Draft = {
  date: string;
  time: string;
  title: string;
  note: string;
  film: FilmBrief | null;
  inEnglish: boolean;
  registration: string;
};

const EMPTY: Draft = {
  date: "",
  time: "19:00",
  title: "",
  note: "",
  film: null,
  inEnglish: false,
  registration: "",
};

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Время события местное: в поля идут части локальной даты, а не UTC из ISO. */
function toDraft(event: ClubEvent): Draft {
  const at = new Date(event.starts_at);
  return {
    date: `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`,
    time: `${pad(at.getHours())}:${pad(at.getMinutes())}`,
    title: event.title ?? "",
    note: event.note ?? "",
    film: event.film,
    inEnglish: event.in_english,
    registration: event.registration_url ?? "",
  };
}

function startsAt(draft: Draft): string {
  return new Date(`${draft.date}T${draft.time || "19:00"}:00`).toISOString();
}

function when(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Поля события. Одни и те же и при создании, и при правке — иначе две формы
 *  разъезжаются, и в одной из них рано или поздно чего-нибудь не хватает. */
function EventFields({
  draft,
  onChange,
  fromCycle = false,
}: {
  draft: Draft;
  onChange(next: Draft): void;
  /** Показ назначен голосованием: время и фильм остаются за циклом, здесь
   *  правятся только подпись, язык и ссылка на регистрацию. */
  fromCycle?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<FilmBrief[]>([]);

  async function lookup() {
    if (query.trim().length < 2) return;
    try {
      setFound((await searchFilms(query.trim())).filter((f) => f.id !== null).slice(0, 5));
    } catch {
      setFound([]);
    }
  }

  return (
    <>
      {/* Время и фильм у показа из цикла выбрало голосование: переносят его
          инструментами расписания, а не правкой поля — иначе матрица и записи
          разъедутся с реальностью. */}
      {!fromCycle && (
        <div className="setting__pair">
          <input
            className="field"
            type="date"
            value={draft.date}
            onChange={(e) => onChange({ ...draft, date: e.target.value })}
          />
          <input
            className="field"
            type="time"
            value={draft.time}
            onChange={(e) => onChange({ ...draft, time: e.target.value })}
          />
        </div>
      )}

      {fromCycle ? null : draft.film ? (
        <div className="slot-row">
          <div>
            <p className="film-row__title">{draft.film.title_ru}</p>
            <p className="meta">{draft.film.year}</p>
          </div>
          <button className="mark" onClick={() => onChange({ ...draft, film: null })}>
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
                onChange({ ...draft, film: item });
                setFound([]);
                setQuery("");
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

      {!fromCycle && (
        <input
          className="field"
          value={draft.title}
          placeholder="Заголовок, если без фильма"
          onChange={(e) => onChange({ ...draft, title: e.target.value })}
        />
      )}
      <input
        className="field"
        value={draft.note}
        placeholder="Подпись, например «ждите анонса»"
        onChange={(e) => onChange({ ...draft, note: e.target.value })}
      />
      {/* Вуз ведёт учёт посещений отдельно от клуба, и ссылка у каждого показа
          своя. Записавшемуся её пришлёт бот, а в приложении рядом с «Приду»
          появится напоминание. */}
      <input
        className="field"
        value={draft.registration}
        placeholder="Ссылка на регистрацию, если она нужна"
        onChange={(e) => onChange({ ...draft, registration: e.target.value })}
      />
      {/* Свойство сеанса, а не фильма: один и тот же фильм клуб может показать
          и с дубляжом, и в оригинале. На этом держится своя ачивка. */}
      <label className="check">
        <input
          type="checkbox"
          checked={draft.inEnglish}
          onChange={(e) => onChange({ ...draft, inEnglish: e.target.checked })}
        />
        Показ на английском
      </label>
    </>
  );
}

/** Правка одного события. Уходит только изменённое: сервер отличает «не трогать
 *  поле» от «очистить его». */
function EventEditor({ event, onDone }: { event: ClubEvent; onDone(): void }) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(event));
  const [reason, setReason] = useState("");
  // Перенос по умолчанию сбрасывает записи (§7): вечер другой — и доступность
  // другая. Но опечатку в дате правят сразу после анонса, и терять из-за неё
  // всех записавшихся жалко, поэтому у переноса есть второй режим.
  const [keepSignups, setKeepSignups] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [busy, setBusy] = useState(false);
  const initial = toDraft(event);

  function changes(): EventChanges {
    const patch: EventChanges = {};
    // У показа из цикла время и фильм менять нельзя — сервер такую правку
    // и не примет, но лучше её и не собирать.
    if (!event.is_manual) {
      if (draft.note.trim() !== (event.note ?? "")) patch.note = draft.note.trim() || null;
      if (draft.inEnglish !== event.in_english) patch.in_english = draft.inEnglish;
      if (draft.registration.trim() !== (event.registration_url ?? "")) {
        patch.registration_url = draft.registration.trim() || null;
      }
      return patch;
    }
    if (draft.date !== initial.date || draft.time !== initial.time) {
      patch.starts_at = startsAt(draft);
    }
    if ((draft.film?.id ?? null) !== event.film_id) patch.film_id = draft.film?.id ?? null;
    if (draft.title.trim() !== (event.title ?? "")) patch.title = draft.title.trim() || null;
    if (draft.note.trim() !== (event.note ?? "")) patch.note = draft.note.trim() || null;
    if (draft.inEnglish !== event.in_english) patch.in_english = draft.inEnglish;
    if (draft.registration.trim() !== (event.registration_url ?? "")) {
      patch.registration_url = draft.registration.trim() || null;
    }
    return patch;
  }

  async function save() {
    const patch = changes();
    if (Object.keys(patch).length === 0) {
      showMessage("Ничего не изменилось");
      return;
    }
    setBusy(true);
    try {
      await updateEvent(event.id, { ...patch, keep_confirmations: keepSignups });
      showMessage(
        patch.starts_at
          ? keepSignups
            ? "Событие перенесено. Записи сохранены, всем ушло уведомление."
            : "Событие перенесено. Подтверждения сброшены, всем ушло уведомление."
          : "Событие обновлено",
      );
      onDone();
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  async function drop() {
    if (!reason.trim()) {
      showMessage("Нужна причина: она уйдёт всем, кто собирался прийти");
      return;
    }
    setBusy(true);
    try {
      await cancelEvent(event.id, reason.trim());
      showMessage("Событие отменено");
      onDone();
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  const fromCycle = !event.is_manual;

  return (
    <>
      {fromCycle && <MoveToEvening event={event} onDone={onDone} />}
      <EventFields draft={draft} onChange={setDraft} fromCycle={fromCycle} />
      {(draft.date !== initial.date || draft.time !== initial.time) && (
        <label className="check">
          <input
            type="checkbox"
            checked={keepSignups}
            onChange={(e) => setKeepSignups(e.target.checked)}
          />
          <span>
            Оставить записи
            <span className="hint">
              {keepSignups
                ? " — тем, кто собирался прийти, придёт просьба отменить, если не смогут"
                : " — иначе все подтверждения сбросятся и отмечаться придётся заново"}
            </span>
          </span>
        </label>
      )}
      <button className="primary" disabled={busy} onClick={save}>
        Сохранить
      </button>

      {cancelling ? (
        <>
          <input
            className="field"
            value={reason}
            placeholder="Причина отмены — её увидят все"
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="marks">
            <button className="mark mark--soon is-on" disabled={busy} onClick={drop}>
              Отменить событие
            </button>
            <button className="mark" disabled={busy} onClick={() => setCancelling(false)}>
              Не отменять
            </button>
          </div>
        </>
      ) : (
        <div className="marks">
          <button className="mark" disabled={busy} onClick={() => setCancelling(true)}>
            Отменить событие
          </button>
        </div>
      )}
    </>
  );
}

/** Перенос показа цикла на другой вечер недели.
 *
 * У него не «время», а слот: вечера задаёт цикл, и назначать показ можно
 * только в них. Поэтому здесь не поле даты, а список свободных вечеров —
 * занятый или заблокированный сервер всё равно не примет.
 *
 * Перенос сбрасывает подтверждения (§7): доступность человек отмечал под
 * конкретный вечер, и молча тащить его на другой нельзя. Записавшимся уходит
 * уведомление.
 */
function MoveToEvening({ event, onDone }: { event: ClubEvent; onDone(): void }) {
  const [slots, setSlots] = useState<Slot[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRound()
      .then((round) => setSlots(round?.slots ?? []))
      // Без списка вечеров переносить некуда — молчим и не показываем блок.
      .catch(() => setSlots([]));
  }, []);

  // Сравниваем моменты, а не строки: сервер отдаёт время с микросекундами
  // и своим смещением, и «тот же вечер» текстом не совпадает сам с собой.
  const now = new Date(event.starts_at).getTime();
  const free = slots.filter(
    (slot) => !slot.blocked && new Date(slot.starts_at).getTime() !== now,
  );
  if (free.length === 0) return null;

  async function move(slot: Slot) {
    if (busy) return;
    const ok = await askConfirm(
      `Перенести на ${when(slot.starts_at)}? Записи сбросятся, всем уйдёт уведомление.`,
    );
    if (!ok) return;
    setBusy(true);
    try {
      await moveScreening(event.id, slot.id);
      showMessage("Показ перенесён, записавшимся ушло уведомление");
      onDone();
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="hint">
        Перенести на другой вечер недели. Записи при этом сбрасываются — вечер
        люди выбирали сами.
      </p>
      <div className="marks">
        {free.map((slot) => (
          <button
            className="mark"
            key={slot.id}
            disabled={busy}
            onClick={() => void move(slot)}
          >
            {when(slot.starts_at)}
          </button>
        ))}
      </div>
    </>
  );
}

/** События клуба: свои, в обход алгоритма (§10), и показы недели.
 *
 * Фильм у своего события необязателен: можно объявить время заранее и раскрыть
 * название позже — ради этого и нужна подпись вроде «ждите анонса».
 *
 * Список общий нарочно: ссылку на регистрацию или пометку «на английском»
 * прикладывают к вечеру независимо от того, выбрало его голосование или админ.
 * Но время и фильм показа из цикла здесь не правятся — их переносят
 * инструментами расписания, иначе матрица разъедется с реальностью.
 */
export function EventPanel({ onCreated }: { onCreated(): void }) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [events, setEvents] = useState<ClubEvent[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    try {
      setEvents(await listEvents());
    } catch {
      // Список — подспорье, а не условие создания события.
      setEvents([]);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function submit() {
    if (busy || !draft.date) return;
    if (!draft.film && !draft.title.trim()) {
      showMessage("Укажите фильм или заголовок события");
      return;
    }
    setBusy(true);
    try {
      await createEvent({
        starts_at: startsAt(draft),
        film_id: draft.film?.id ?? null,
        title: draft.title.trim() || null,
        note: draft.note.trim() || null,
        in_english: draft.inEnglish,
        registration_url: draft.registration.trim() || null,
      });
      setDraft(EMPTY);
      showMessage("Событие создано");
      await reload();
      onCreated();
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {events.length > 0 && (
        <Section
          title="Назначенные события"
          count={events.length}
          storageKey="admin-events"
          hint="Здесь и свои события, и показы недели: ссылку на регистрацию прикладывают к любому."
        >
          {events.map((event) => (
            <div className="slot-row" key={event.id} style={{ display: "block" }}>
              <p className="film-row__title">
                {event.film?.title_ru ?? event.title ?? "Без названия"}
              </p>
              <p className="meta">
                {when(event.starts_at)}
                {event.confirmed > 0 && ` · придут ${event.confirmed}`}
                {/* Откуда взялся вечер — от этого зависит, что в нём правится. */}
                {!event.is_manual && " · из цикла"}
              </p>
              {event.note && <p className="hint">{event.note}</p>}
              {editing === event.id ? (
                <EventEditor
                  event={event}
                  onDone={async () => {
                    setEditing(null);
                    await reload();
                  }}
                />
              ) : (
                <div className="marks">
                  <button className="mark" onClick={() => setEditing(event.id)}>
                    Изменить
                  </button>
                </div>
              )}
            </div>
          ))}
        </Section>
      )}

      <h3>Своё событие</h3>
      <p className="hint">
        Назначается на любое время, минуя алгоритм. Фильм можно не указывать —
        тогда напишите заголовок и подпись.
      </p>

      <EventFields draft={draft} onChange={setDraft} />

      <button className="primary" disabled={busy || !draft.date} onClick={submit}>
        Создать событие
      </button>
    </>
  );
}

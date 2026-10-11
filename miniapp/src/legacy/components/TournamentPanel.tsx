import { useEffect, useState } from "react";
import {
  ApiError,
  cancelTournament,
  createTournament,
  getTournament,
  listTournaments,
  searchFilms,
  setTournamentOptions,
  startTournament,
} from "../api";
import { haptic, showMessage } from "../telegram";
import type { FilmBrief, Tournament, TournamentBrief, TournamentOptionDraft } from "../types";

// Сетка сходится только при степени двойки: «технические поражения»
// в развлечении лишние, а объяснять их пришлось бы каждому.
const SIZES = [4, 8, 16, 32];

function isReady(count: number): boolean {
  return SIZES.includes(count);
}

/** Админская часть турниров: завести, набрать варианты, запустить.
 *
 * Вариант — либо фильм из каталога (название и постер подтянутся сами), либо
 * своя карточка: персонажа или сцену в каталоге не найти.
 */
export function TournamentPanel() {
  const [list, setList] = useState<TournamentBrief[]>([]);
  const [draft, setDraft] = useState<Tournament | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [options, setOptions] = useState<TournamentOptionDraft[]>([]);
  const [manual, setManual] = useState("");
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<FilmBrief[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTournaments().then(setList).catch(() => {});
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setFound([]);
      return;
    }
    let alive = true;
    const timer = setTimeout(() => {
      searchFilms(trimmed)
        .then((films) => alive && setFound(films.slice(0, 5)))
        .catch(() => alive && setFound([]));
    }, 350);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [query]);

  async function guard(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      haptic();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Не получилось";
      setError(message);
      showMessage(message);
    } finally {
      setBusy(false);
    }
  }

  const open = (tournament: Tournament) => {
    setDraft(tournament);
    setTitle(tournament.title);
    setDescription(tournament.description ?? "");
    setOptions(
      tournament.rounds
        .flatMap((round) => round.matches)
        .flatMap((match) => [match.option_a, match.option_b])
        .filter((option) => option !== null)
        .map((option) => ({
          title: option.title,
          subtitle: option.subtitle,
          image_url: option.image_url,
          film_id: option.film_id,
        })),
    );
  };

  const create = () =>
    guard(async () => {
      const created = await createTournament(title.trim(), description.trim() || null);
      setDraft(created);
      setOptions([]);
      setList(await listTournaments());
    });

  const save = () =>
    guard(async () => {
      if (!draft) return;
      setDraft(await setTournamentOptions(draft.id, options));
    });

  const launch = () =>
    guard(async () => {
      if (!draft) return;
      await setTournamentOptions(draft.id, options);
      setDraft(await startTournament(draft.id));
      setList(await listTournaments());
    });

  const stop = (id: number) =>
    guard(async () => {
      await cancelTournament(id);
      setDraft(null);
      setList(await listTournaments());
    });

  const add = (option: TournamentOptionDraft) => {
    setOptions((current) => [...current, option]);
    setQuery("");
    setFound([]);
    setManual("");
  };

  const running = list.find((item) => item.status === "running");

  return (
    <>
      {error && <div className="error">{error}</div>}

      {running && (
        <div className="slot-row">
          <div>
            <p className="film-row__title">🏆 {running.title}</p>
            <p className="meta">идёт сейчас</p>
          </div>
          <button className="mark" disabled={busy} onClick={() => void stop(running.id)}>
            Отменить
          </button>
        </div>
      )}

      {draft === null ? (
        <>
          <h3>Новый турнир</h3>
          <p className="hint">
            Тема — то, что выбирают: «лучший злодей», «лучшая комедия». Дальше наберите
            варианты: {SIZES.join(", ")} — сетка должна сходиться.
          </p>
          <input
            className="field"
            value={title}
            placeholder="Тема турнира"
            onChange={(event) => setTitle(event.target.value)}
          />
          <textarea
            className="field"
            rows={2}
            value={description}
            placeholder="Описание, если нужно"
            onChange={(event) => setDescription(event.target.value)}
          />
          <button className="primary" disabled={busy || !title.trim()} onClick={() => void create()}>
            Создать черновик
          </button>

          {list.filter((item) => item.status === "draft").length > 0 && (
            <>
              <h3>Черновики</h3>
              {list
                .filter((item) => item.status === "draft")
                .map((item) => (
                  <button
                    className="slot-row"
                    key={item.id}
                    disabled={busy}
                    onClick={() => void guard(async () => open(await getTournament(item.id)))}
                  >
                    <span className="film-row__title">{item.title}</span>
                    <span className="hint">→</span>
                  </button>
                ))}
            </>
          )}
        </>
      ) : (
        <>
          <div className="profile__row">
            <h3 style={{ margin: 0 }}>{draft.title}</h3>
            <button className="mark" onClick={() => setDraft(null)}>
              ← К списку
            </button>
          </div>

          <p className="hint">
            Вариантов: {options.length}
            {isReady(options.length)
              ? " — сетка сходится, можно запускать."
              : ` — нужно ${SIZES.find((size) => size > options.length) ?? SIZES[0]}.`}
            {" "}Порядок задаёт посев: первый встретится с последним.
          </p>

          {options.map((option, index) => (
            <div className="slot-row" key={`${option.title}-${index}`}>
              <span>
                {index + 1}. {option.title || "Фильм из каталога"}
                {option.film_id && <span className="meta"> · из каталога</span>}
              </span>
              <button
                className="mark"
                disabled={busy}
                onClick={() => setOptions((current) => current.filter((_, i) => i !== index))}
              >
                ✕
              </button>
            </div>
          ))}

          <h3>Добавить фильм из каталога</h3>
          <input
            className="field"
            value={query}
            placeholder="Найти фильм"
            onChange={(event) => setQuery(event.target.value)}
          />
          {found.map((film) => (
            <button
              className="slot-row"
              key={film.id ?? `tmdb-${film.tmdb_id}`}
              disabled={busy || film.id === null}
              onClick={() => add({ title: film.title_ru, film_id: film.id })}
            >
              <span>
                {film.title_ru} <span className="meta">{film.year}</span>
              </span>
              {/* Фильма ещё нет в каталоге: в турнир он попадёт, только когда
                  кто-нибудь заведёт его отметкой — иначе постер брать неоткуда. */}
              <span className="hint">{film.id === null ? "не в каталоге" : "+"}</span>
            </button>
          ))}

          <h3>Или своя карточка</h3>
          <input
            className="field"
            value={manual}
            placeholder="Например, «Ганнибал Лектер»"
            onChange={(event) => setManual(event.target.value)}
          />
          <button
            className="mark"
            disabled={busy || !manual.trim()}
            onClick={() => add({ title: manual.trim() })}
          >
            Добавить вариант
          </button>

          <div className="marks" style={{ marginTop: 12 }}>
            <button className="mark" disabled={busy} onClick={() => void save()}>
              Сохранить
            </button>
            <button
              className="primary"
              disabled={busy || !isReady(options.length)}
              onClick={() => void launch()}
            >
              Запустить турнир
            </button>
          </div>
        </>
      )}
    </>
  );
}

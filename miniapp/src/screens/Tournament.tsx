import { useEffect, useState } from "react";
import { ApiError, getTournament, voteInTournament } from "../api";
import { BackLink } from "../components/BackLink";
import { haptic, showMessage } from "../telegram";
import type { Tournament as Data, TournamentMatch, TournamentOption } from "../types";

/** Сколько осталось до конца этапа — словами, а не таймером.
 *
 * Секунды здесь не нужны: этап длится сутки, и «через 4 ч» говорит ровно
 * столько же, сколько бегущие цифры, но не заставляет экран перерисовываться.
 */
export function timeLeft(closesAt: string): string {
  const ms = new Date(closesAt).getTime() - Date.now();
  if (ms <= 0) return "этап закрывается";
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 24) return `${Math.floor(hours / 24)} дн`;
  if (hours >= 1) return `${hours} ч`;
  return `${Math.max(1, Math.round(ms / 60_000))} мин`;
}

function Side({
  option,
  chosen,
  votes,
  won,
  disabled,
  onPick,
}: {
  option: TournamentOption | null;
  chosen: boolean;
  votes: number | null;
  won: boolean;
  disabled: boolean;
  onPick?(): void;
}) {
  if (option === null) return <div className="duel__side duel__side--empty">—</div>;

  const classes = ["duel__side"];
  if (chosen) classes.push("is-chosen");
  if (won) classes.push("is-won");

  return (
    <button className={classes.join(" ")} disabled={disabled} onClick={onPick}>
      {option.image_url ? (
        <img className="duel__poster" src={option.image_url} alt="" loading="lazy" />
      ) : (
        // Своя карточка часто без картинки — под неё не резервируем место
        // постера: четыре пустых прямоугольника 2:3 занимают весь экран.
        <span className="duel__poster duel__poster--empty">
          {option.title.trim().charAt(0).toUpperCase()}
        </span>
      )}
      <span className="duel__title">{option.title}</span>
      {option.subtitle && <span className="meta">{option.subtitle}</span>}
      {/* Счёт появляется только после закрытия этапа. */}
      {votes !== null && <span className="duel__votes">{votes}</span>}
    </button>
  );
}

function Duel({
  match,
  live,
  busy,
  onPick,
}: {
  match: TournamentMatch;
  live: boolean;
  busy: boolean;
  onPick(matchId: number, optionId: number): void;
}) {
  return (
    <div className="duel">
      <Side
        option={match.option_a}
        chosen={match.my_option_id === match.option_a?.id}
        votes={match.votes_a}
        won={match.winner_option_id !== null && match.winner_option_id === match.option_a?.id}
        disabled={!live || busy}
        onPick={() => match.option_a && onPick(match.id, match.option_a.id)}
      />
      <span className="duel__vs">vs</span>
      <Side
        option={match.option_b}
        chosen={match.my_option_id === match.option_b?.id}
        votes={match.votes_b}
        won={match.winner_option_id !== null && match.winner_option_id === match.option_b?.id}
        disabled={!live || busy}
        onPick={() => match.option_b && onPick(match.id, match.option_b.id)}
      />
    </div>
  );
}

/** Экран турнира: текущий этап парами, ниже — сыгранное.
 *
 * Голос ставится одним нажатием и меняется до конца этапа. Пока этап идёт,
 * чужих голосов не видно: счёт на глазах у голосующих превращает выбор
 * в присоединение к большинству — по той же причине каталог не сортируется
 * по популярности (§11).
 */
export function Tournament({ id, onBack }: { id: number; onBack(): void }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getTournament(id)
      .then((next) => alive && setData(next))
      .catch((e) => alive && setError(e instanceof Error ? e.message : "Не удалось загрузить"));
    return () => {
      alive = false;
    };
  }, [id]);

  async function pick(matchId: number, optionId: number) {
    if (busy) return;
    setBusy(true);
    // Оптимистично: голос — это одно нажатие, и ждать ответа, глядя на
    // неизменившуюся карточку, неприятно. Ошибку откатываем ответом сервера.
    setData((current) =>
      current
        ? {
            ...current,
            rounds: current.rounds.map((round) => ({
              ...round,
              matches: round.matches.map((match) =>
                match.id === matchId ? { ...match, my_option_id: optionId } : match,
              ),
            })),
          }
        : current,
    );
    haptic();
    try {
      setData(await voteInTournament(id, matchId, optionId));
    } catch (e) {
      showMessage(e instanceof ApiError ? e.message : "Голос не сохранился");
      setData(await getTournament(id));
    } finally {
      setBusy(false);
    }
  }

  if (error)
    return (
      <div className="screen">
        <BackLink onBack={onBack} />
        <div className="error">{error}</div>
      </div>
    );
  if (!data) return <div className="center">Загрузка…</div>;

  const live = data.rounds.find((round) => round.round_no === data.current_round);
  const played = data.rounds.filter((round) => round.closed).reverse();

  return (
    <div className="screen">
      <BackLink onBack={onBack} />

      <h1 style={{ fontSize: 20, margin: 0 }}>🏆 {data.title}</h1>
      {data.description && <p className="hint">{data.description}</p>}

      {data.winner && (
        <div className="tournament__winner">
          <span className="meta">Победитель турнира</span>
          <b>{data.winner.title}</b>
        </div>
      )}

      {live && (
        <>
          <div className="profile__row">
            <h3 style={{ margin: 0 }}>{live.name}</h3>
            {data.closes_at && <span className="hint">осталось {timeLeft(data.closes_at)}</span>}
          </div>
          <p className="hint">
            {data.left_to_vote > 0
              ? "Выберите в каждой паре того, кто пройдёт дальше. Передумать можно до конца этапа."
              : "Вы отголосовали все пары. Итоги — когда этап закроется."}
          </p>
          {live.matches.map((match) => (
            <Duel key={match.id} match={match} live busy={busy} onPick={pick} />
          ))}
        </>
      )}

      {played.map((round) => (
        <div key={round.round_no}>
          <h3>{round.name} · сыгран</h3>
          {round.matches.map((match) => (
            <Duel key={match.id} match={match} live={false} busy={busy} onPick={pick} />
          ))}
        </div>
      ))}
    </div>
  );
}

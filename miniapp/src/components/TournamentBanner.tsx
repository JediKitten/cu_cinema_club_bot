import { currentTournament } from "../api";
import { timeLeft } from "../screens/Tournament";
import { useLoad } from "../useLoad";

/** Плашка идущего турнира — вверху каталога и расписания.
 *
 * Турнир живёт этапами по суткам, и человек, открывший приложение не в тот
 * день, просто не узнает о нём. Плашка показывается, только когда есть что
 * открыть, и прямо говорит, сколько пар осталось и сколько времени.
 */
export function TournamentBanner({ onOpen }: { onOpen(id: number): void }) {
  // Ошибку молча пропускаем: турнир — не то, ради чего стоит показывать
  // ошибку поверх каталога.
  const { data: tournament } = useLoad(currentTournament, []);

  if (!tournament) return null;

  return (
    <button className="tournament-banner" onClick={() => onOpen(tournament.id)}>
      <span className="tournament-banner__icon">🏆</span>
      <span className="tournament-banner__text">
        <b>{tournament.title}</b>
        <span className="meta">
          {tournament.left_to_vote > 0
            ? `Не отголосовано пар: ${tournament.left_to_vote}`
            : "Голос учтён — ждём итогов этапа"}
          {tournament.closes_at && ` · осталось ${timeLeft(tournament.closes_at)}`}
        </span>
      </span>
      <span className="hint">→</span>
    </button>
  );
}

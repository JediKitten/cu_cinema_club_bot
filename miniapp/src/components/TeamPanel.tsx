import { useEffect, useState } from "react";
import { ApiError, findUsers, getGrantableRoles, getTeam, setUserRole } from "../api";
import { showMessage } from "../telegram";
import type { Role, TeamMember } from "../types";

const ROLE_LABEL: Record<Role, string> = {
  user: "участник",
  moderator: "модератор",
  admin: "администратор",
  superadmin: "главный администратор",
};

/** Назначение ролей (§9).
 *
 * Какие роли доступны — решает сервер: админ выдаёт модераторов, главный админ
 * ещё и администраторов. Список приходит оттуда, чтобы правило жило в одном месте.
 */
export function TeamPanel() {
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [grantable, setGrantable] = useState<Role[]>([]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<TeamMember[]>([]);
  const [busy, setBusy] = useState(false);

  async function reload() {
    const [members, roles] = await Promise.all([getTeam(), getGrantableRoles()]);
    setTeam(members);
    setGrantable(roles);
  }

  useEffect(() => {
    reload().catch(() => showMessage("Не удалось загрузить команду"));
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setFound([]);
      return;
    }
    const timer = setTimeout(() => {
      findUsers(trimmed).then(setFound).catch(() => setFound([]));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  async function assign(user: TeamMember, role: Role) {
    if (busy) return;
    setBusy(true);
    try {
      await setUserRole(user.id, role);
      await reload();
      setQuery("");
      setFound([]);
    } catch (error) {
      showMessage(error instanceof ApiError ? error.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  function RoleButtons({ member }: { member: TeamMember }) {
    return (
      <div className="marks" style={{ marginTop: 6 }}>
        {grantable.map((role) => (
          <button
            key={role}
            className={`mark ${member.role === role ? "is-on mark--wishlist" : ""}`}
            disabled={busy || member.role === role || member.role === "superadmin"}
            onClick={() => assign(member, role)}
          >
            {ROLE_LABEL[role]}
          </button>
        ))}
      </div>
    );
  }

  return (
    <>
      <h3>Команда</h3>
      {team.map((member) => (
        <div className="slot-row" key={member.id} style={{ display: "block" }}>
          <p className="film-row__title">
            {member.display_name}
            {member.tg_username && <span className="hint"> @{member.tg_username}</span>}
          </p>
          <p className="meta">{ROLE_LABEL[member.role]}</p>
          {member.role !== "superadmin" && <RoleButtons member={member} />}
        </div>
      ))}

      <h3>Назначить кого-то ещё</h3>
      <input
        className="field"
        value={query}
        placeholder="Имя или @username"
        onChange={(event) => setQuery(event.target.value)}
      />
      {query.trim().length >= 2 && found.length === 0 && (
        // Человек должен хотя бы раз открыть приложение — только тогда у него
        // появляется аккаунт, который можно повысить.
        <p className="hint">Никого не нашли. Человек должен хотя бы раз зайти в приложение.</p>
      )}
      {found.map((member) => (
        <div className="slot-row" key={member.id} style={{ display: "block" }}>
          <p className="film-row__title">
            {member.display_name}
            {member.tg_username && <span className="hint"> @{member.tg_username}</span>}
          </p>
          <p className="meta">сейчас: {ROLE_LABEL[member.role]}</p>
          <RoleButtons member={member} />
        </div>
      ))}
    </>
  );
}

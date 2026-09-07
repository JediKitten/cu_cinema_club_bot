import { useEffect, useState } from "react";
import { ApiError, findUsers, getGrantableRoles, getTeam, setUserRole } from "../api";
import { ROLE_LABEL } from "../roles";
import { showMessage } from "../telegram";
import type { Role, TeamMember, User } from "../types";

// Тот же порядок, что и на сервере: менять роль можно только тому, кто ниже вас.
const RANK: Record<Role, number> = { user: 0, moderator: 1, admin: 2, superadmin: 3 };

/** Назначение ролей (§9).
 *
 * Какие роли доступны — решает сервер: админ выдаёт модераторов, главный админ
 * ещё и администраторов. Список приходит оттуда, чтобы правило жило в одном месте.
 */
export function TeamPanel({ me }: { me: User }) {
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

  /** Кого этот администратор вправе трогать.
   *
   * Себя — нельзя: клуб остался бы без главного админа, и вернуть роль было бы
   * некому. Равного — тоже: иначе разжалование превращается в гонку, где прав
   * тот, кто нажал первым. Правило то же, что на сервере; здесь оно только
   * убирает кнопки, которые всё равно ответили бы отказом.
   */
  function editable(member: TeamMember): boolean {
    return member.id !== me.id && RANK[member.role] < RANK[me.role];
  }

  function RoleButtons({ member }: { member: TeamMember }) {
    if (!editable(member)) return null;
    return (
      <div className="marks" style={{ marginTop: 6 }}>
        {grantable.map((role) => (
          <button
            key={role}
            className={`mark ${member.role === role ? "is-on mark--wishlist" : ""}`}
            disabled={busy || member.role === role}
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
          <p className="meta">
            {ROLE_LABEL[member.role]}
            {member.id === me.id && " · это вы"}
          </p>
          <RoleButtons member={member} />
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
          {editable(member) ? (
            <RoleButtons member={member} />
          ) : (
            <p className="hint">Роль этого человека вам менять нельзя.</p>
          )}
        </div>
      ))}
    </>
  );
}

import { useEffect, useState } from "react";
import { getPeople } from "../api";
import type { PersonRow, Role } from "../types";

const ROLE_LABEL: Record<Role, string> = {
  user: "участник",
  moderator: "модератор",
  admin: "администратор",
  superadmin: "главный администратор",
};

/** Все участники клуба и то, как каждый сюда попал (просьба клуба).
 *
 * Вопрос не праздный: на бете важно видеть, чей код разошёлся и кто ещё стоит
 * за дверью.
 */
export function PeoplePanel() {
  const [people, setPeople] = useState<PersonRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    getPeople()
      .then(setPeople)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  if (error) return <div className="error">{error}</div>;

  const needle = query.trim().toLowerCase();
  const shown = needle
    ? people.filter(
        (person) =>
          person.display_name.toLowerCase().includes(needle) ||
          (person.tg_username ?? "").toLowerCase().includes(needle) ||
          (person.invite_code ?? "").toLowerCase().includes(needle),
      )
    : people;

  return (
    <>
      <h3>Участники · {people.length}</h3>
      <input
        className="field"
        value={query}
        placeholder="Имя, @username или код"
        onChange={(event) => setQuery(event.target.value)}
      />

      {shown.map((person) => (
        <div className="slot-row" key={person.id} style={{ display: "block" }}>
          <p className="film-row__title">
            {person.display_name}
            {person.tg_username && <span className="hint"> @{person.tg_username}</span>}
          </p>
          <p className="meta">
            {ROLE_LABEL[person.role]} · с{" "}
            {new Date(person.created_at).toLocaleDateString("ru-RU")}
          </p>
          <p className="meta">
            {!person.has_access
              ? "⏳ ждёт кода"
              : person.invite_code
                ? `по коду ${person.invite_code} · выдал ${person.invited_by ?? "—"}`
                : "без кода — был до беты"}
          </p>
        </div>
      ))}
      {shown.length === 0 && <p className="hint">Никого не нашли.</p>}
    </>
  );
}

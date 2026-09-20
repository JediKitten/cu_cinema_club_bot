import { useEffect, useState } from "react";
import { getPeople } from "../api";
import { ROLE_LABEL } from "../roles";
import type { PersonRow } from "../types";

/** Все участники клуба: кто, с каким ником, с какой роли и с какого дня.
 *
 * Список с поиском, а не выгрузка: найти человека глазами в полутора сотнях
 * строк нельзя, а зайти сюда надо ровно затем, чтобы найти одного.
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
          (person.tg_username ?? "").toLowerCase().includes(needle),
      )
    : people;

  return (
    <>
      <h3>Участники · {people.length}</h3>
      <input
        className="field"
        value={query}
        placeholder="Имя или @username"
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
        </div>
      ))}
      {shown.length === 0 && <p className="hint">Никого не нашли.</p>}
    </>
  );
}

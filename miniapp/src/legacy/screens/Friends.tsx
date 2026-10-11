import { useEffect, useState } from "react";
import { addFriend, findPeople, getCircle, getFeed, listMembers, removeFriend } from "../api";
import { Poster } from "../components/FilmRow";
import { Section } from "../components/Section";
import { useOpenFilmById } from "../filmOpener";
import { haptic, showMessage } from "../telegram";
import { Avatar } from "./Profile";
import type { Circle, FeedItem, PersonBrief } from "../types";
import { useSearch } from "../useLoad";

const ACTION: Record<FeedItem["kind"], string> = {
  rating: "оценил",
  review: "написал отзыв",
  wishlist: "хочет посмотреть",
  soon: "готов пойти в ближайшее",
  watched: "посмотрел",
};

function when(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "сегодня";
  if (days === 1) return "вчера";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

/** Друзья и их лента.
 *
 * Лента собрана из событий, которые и так есть: отметок, просмотров и оценок.
 * Ничего нового ради неё не сохраняется.
 */
export function Friends({ onOpenProfile }: { onOpenProfile(id: number): void }) {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [circle, setCircle] = useState<Circle | null>(null);
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<PersonBrief[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openFilm = useOpenFilmById();

  async function reload() {
    const [items, groups, everyone] = await Promise.all([getFeed(), getCircle(), listMembers()]);
    setFeed(items);
    setCircle(groups);
    setPeople(everyone);
  }

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  const { found, setFound } = useSearch(query, findPeople);

  async function toggle(person: PersonBrief) {
    if (busy) return;
    setBusy(true);
    try {
      const updated = person.following
        ? await removeFriend(person.id)
        : await addFriend(person.id);
      haptic();
      const patch = (rows: PersonBrief[]) =>
        rows.map((row) => (row.id === updated.id ? { ...row, ...updated } : row));
      setFound(patch);
      setPeople(patch);
      await reload();
    } catch (e) {
      showMessage(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  function Person({ person, action }: { person: PersonBrief; action?: boolean }) {
    return (
      <div className="slot-row person-row" key={person.id}>
        <button className="person-row__main" onClick={() => onOpenProfile(person.id)}>
          <Avatar url={person.photo_url} name={person.display_name} size={40} />
          <div>
            <p className="film-row__title">{person.display_name}</p>
            {person.tg_username && <p className="meta">@{person.tg_username}</p>}
          </div>
        </button>
        {action && (
          <button
            className={`mark ${person.following ? "is-on mark--wishlist" : ""}`}
            disabled={busy}
            onClick={() => toggle(person)}
          >
            {person.friends
              ? "✓ В друзьях"
              : person.following
                ? "✓ Добавлен"
                : person.follower
                  ? "Добавить в ответ"
                  : "Добавить"}
          </button>
        )}
      </div>
    );
  }

  if (error) return <div className="screen"><div className="error">{error}</div></div>;

  return (
    <div className="screen">
      {/* Строки «мой профиль» здесь больше нет: на этот экран приходят из
          профиля, и она вела бы ровно туда, откуда человек только что вышел. */}
      <input
        className="field"
        value={query}
        placeholder="Найти участника по имени или @username"
        onChange={(event) => setQuery(event.target.value)}
      />
      {query.trim().length >= 2 && found.length === 0 && (
        <p className="hint">Никого не нашли.</p>
      )}
      {found.map((person) => (
        <Person key={person.id} person={person} action />
      ))}

      {/* Весь клуб под поиском. Свёрнут по умолчанию: список на полсотни имён
          закрыл бы собой друзей и ленту, а искать поиском можно, только если
          знаешь, кого ищешь, — новичок не знает никого. */}
      {people.length > 0 && (
        <Section
          title="Все участники"
          count={people.length}
          storageKey="people-all"
          defaultOpen={false}
        >
          {people.map((person) => (
            <Person key={person.id} person={person} action />
          ))}
        </Section>
      )}

      {circle && circle.friends.length > 0 && (
        <Section title="В друзьях" count={circle.friends.length} storageKey="circle-friends">
          {circle.friends.map((person) => (
            <Person key={person.id} person={person} action />
          ))}
        </Section>
      )}

      {circle && circle.following.length > 0 && (
        <Section
          title="Вы подписаны"
          count={circle.following.length}
          storageKey="circle-following"
          hint="Пока в одну сторону: станет дружбой, когда добавят в ответ."
        >
          {circle.following.map((person) => (
            <Person key={person.id} person={person} action />
          ))}
        </Section>
      )}

      {circle && circle.followers.length > 0 && (
        <Section
          title="Подписаны на вас"
          count={circle.followers.length}
          storageKey="circle-followers"
        >
          {circle.followers.map((person) => (
            <Person key={person.id} person={person} action />
          ))}
        </Section>
      )}

      <h3>Что у друзей</h3>
      {feed.length === 0 && (
        <p className="hint">
          Пусто. Добавьте кого-нибудь — и увидите, что они отмечают и как оценивают.
        </p>
      )}
      {feed.map((item, index) => (
        <div
          className="film-row film-row--clickable"
          key={`${item.kind}-${item.user_id}-${item.film_id}-${index}`}
          onClick={() => openFilm(item.film_id, item.film_title)}
        >
          <Poster url={item.film_poster} />
          <div>
            <p className="film-row__title">{item.film_title}</p>
            <p className="meta">
              {item.user_name} {ACTION[item.kind]}
              {item.rating !== null && ` · ${item.rating.toFixed(1)} ★`}
            </p>
            {item.text && <p className="meta">{item.text}</p>}
            <p className="meta">{when(item.at)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

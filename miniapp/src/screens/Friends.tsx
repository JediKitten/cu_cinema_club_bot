import { useEffect, useState } from "react";
import { addFriend, findPeople, getCircle, getFeed, removeFriend } from "../api";
import { Poster } from "../components/FilmRow";
import { Section } from "../components/Section";
import { useOpenFilmById } from "../filmOpener";
import { haptic, showMessage } from "../telegram";
import { Avatar } from "./Profile";
import type { Circle, FeedItem, PersonBrief, User } from "../types";

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
export function Friends({
  me,
  onOpenProfile,
}: {
  me: User;
  onOpenProfile(id: number): void;
}) {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [circle, setCircle] = useState<Circle | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<PersonBrief[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openFilm = useOpenFilmById();

  async function reload() {
    const [items, groups] = await Promise.all([getFeed(), getCircle()]);
    setFeed(items);
    setCircle(groups);
  }

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setFound([]);
      return;
    }
    const timer = setTimeout(() => {
      findPeople(trimmed).then(setFound).catch(() => setFound([]));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  async function toggle(person: PersonBrief) {
    if (busy) return;
    setBusy(true);
    try {
      const updated = person.following
        ? await removeFriend(person.id)
        : await addFriend(person.id);
      haptic();
      setFound((current) =>
        current.map((row) => (row.id === updated.id ? { ...row, ...updated } : row)),
      );
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
      {/* Свой профиль живёт здесь же: настройка профиля и люди клуба — одно
          и то же занятие, и разносить их по разным вкладкам незачем. */}
      <button className="slot-row person-row" onClick={() => onOpenProfile(me.id)}>
        <span className="person-row__main">
          <Avatar url={me.photo_url} name={me.display_name} size={44} />
          <span>
            <p className="film-row__title">{me.display_name}</p>
            <p className="meta">
              {me.tg_username ? `@${me.tg_username} · ` : ""}
              мой профиль и любимые фильмы
            </p>
          </span>
        </span>
        <span className="hint">→</span>
      </button>

      <h2 style={{ fontSize: 18, margin: 0 }}>Друзья</h2>
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

import { useEffect, useState } from "react";
import { addFriend, getProfile, removeFriend, searchFilms, setFavourites } from "../api";
import { Poster } from "../components/FilmRow";
import { useOpenFilm } from "../filmOpener";
import { haptic, showMessage, useTelegramBackButton } from "../telegram";
import { plural } from "../plural";
import { ROLE_LABEL } from "../roles";
import type { FilmBrief, Profile as Data } from "../types";

const MAX_FAVOURITES = 4;

const ACTION: Record<string, string> = {
  rating: "оценил",
  review: "написал отзыв",
  wishlist: "хочет посмотреть",
  soon: "готов пойти в ближайшее время",
  watched: "посмотрел",
};

export function Avatar({ url, name, size = 48 }: { url: string | null; name: string; size?: number }) {
  return url ? (
    <img className="avatar" src={url} alt="" style={{ width: size, height: size }} />
  ) : (
    // Телеграм отдаёт фото не всем: у закрытых профилей его просто нет.
    <div className="avatar avatar--empty" style={{ width: size, height: size }}>
      {name.trim().charAt(0).toUpperCase() || "?"}
    </div>
  );
}

/** Профиль участника клуба.
 *
 * Свой профиль отличается только тем, что четыре любимых фильма в нём можно
 * поменять: смотреть на чужой вкус интереснее, чем на собственный.
 */
export function Profile({
  userId,
  active = true,
  onBack,
}: {
  userId: number;
  /** Экран остаётся смонтированным под карточкой фильма — но кнопка «назад»
   *  в это время принадлежит карточке, а не ему. */
  active?: boolean;
  onBack(): void;
}) {
  const [profile, setProfile] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<FilmBrief[]>([]);
  const openFilm = useOpenFilm();

  useEffect(() => useTelegramBackButton(active, onBack), [active, onBack]);

  useEffect(() => {
    let alive = true;
    getProfile(userId)
      .then((data) => alive && setProfile(data))
      .catch((e) => alive && setError(e instanceof Error ? e.message : "Не удалось загрузить"));
    return () => {
      alive = false;
    };
  }, [userId]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!editing || trimmed.length < 2) {
      setFound([]);
      return;
    }
    const timer = setTimeout(() => {
      searchFilms(trimmed)
        .then((films) => setFound(films.filter((film) => film.id !== null).slice(0, 6)))
        .catch(() => setFound([]));
    }, 350);
    return () => clearTimeout(timer);
  }, [query, editing]);

  async function toggleFriend() {
    if (!profile || busy) return;
    setBusy(true);
    try {
      const relation = profile.relation_following
        ? await removeFriend(profile.id)
        : await addFriend(profile.id);
      haptic();
      setProfile({
        ...profile,
        relation_following: relation.following,
        relation_follower: relation.follower,
        relation_friends: relation.friends,
      });
    } catch (e) {
      showMessage(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  async function saveFavourites(films: FilmBrief[]) {
    if (!profile) return;
    setBusy(true);
    try {
      const saved = await setFavourites(films.map((film) => film.id!).filter(Boolean));
      setProfile({ ...profile, favourites: saved });
      setQuery("");
      setFound([]);
    } catch (e) {
      showMessage(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="screen"><div className="error">{error}</div></div>;
  if (!profile) return <div className="center">Загрузка…</div>;

  const relation = profile.relation_friends
    ? "в друзьях"
    : profile.relation_following
      ? "вы подписаны"
      : profile.relation_follower
        ? "подписан на вас"
        : null;

  return (
    <div className="screen">
      <div className="profile__head">
        <Avatar url={profile.photo_url} name={profile.display_name} size={64} />
        <div>
          <h1 style={{ fontSize: 20, margin: 0 }}>{profile.display_name}</h1>
          {profile.tg_username && <p className="meta">@{profile.tg_username}</p>}
          <p className="meta">
            {ROLE_LABEL[profile.role]}
            {relation && ` · ${relation}`}
          </p>
        </div>
      </div>

      {!profile.is_me && (
        <div className="marks">
          <button
            className={`mark ${profile.relation_following ? "is-on mark--wishlist" : ""}`}
            disabled={busy}
            onClick={toggleFriend}
          >
            {profile.relation_friends
              ? "✓ В друзьях"
              : profile.relation_following
                ? "✓ Вы подписаны"
                : profile.relation_follower
                  ? "Добавить в ответ"
                  : "Добавить в друзья"}
          </button>
        </div>
      )}

      <div className="stats-grid">
        <div className="stat">
          <b>{profile.marks}</b>
          <span>{plural(profile.marks, ["отметка", "отметки", "отметок"])}</span>
        </div>
        <div className="stat">
          <b>{profile.watched}</b>
          <span>просмотрено</span>
        </div>
        <div className="stat">
          <b>{profile.average_rating ?? "—"}</b>
          <span>
            {profile.ratings} {plural(profile.ratings, ["оценка", "оценки", "оценок"])}
          </span>
        </div>
        <div className="stat">
          <b>{profile.friends}</b>
          <span>{plural(profile.friends, ["друг", "друга", "друзей"])}</span>
        </div>
      </div>

      <div className="profile__row">
        <h3 style={{ margin: 0 }}>Любимое</h3>
        {profile.is_me && (
          <button className="mark" onClick={() => setEditing((value) => !value)}>
            {editing ? "Готово" : "Изменить"}
          </button>
        )}
      </div>

      {profile.favourites.length === 0 && !editing && (
        <p className="hint">
          {profile.is_me
            ? `Выберите до ${MAX_FAVOURITES} фильмов — их увидят все, кто откроет ваш профиль.`
            : "Пока ничего не выбрано."}
        </p>
      )}

      <div className="poster-grid">
        {profile.favourites.map((film) => (
          <button
            className="poster-grid__item"
            key={film.id}
            onClick={() => (editing ? undefined : openFilm(film))}
            title={film.title_ru}
          >
            <Poster url={film.poster_url} className="poster--tile" />
            {editing && <span className="poster-grid__remove">✕</span>}
          </button>
        ))}

        {/* Пустые места видно: четыре плитки — это витрина, и незаполненная
            говорит, что её можно занять, а не что здесь ничего нет. */}
        {Array.from({ length: MAX_FAVOURITES - profile.favourites.length }).map((_, index) => (
          <button
            className="poster-grid__item poster-grid__item--empty"
            key={`empty-${index}`}
            disabled={!profile.is_me}
            onClick={() => setEditing(true)}
            title={profile.is_me ? "Добавить любимый фильм" : "Место свободно"}
          >
            <span className="poster poster--tile poster--slot">{profile.is_me ? "+" : ""}</span>
          </button>
        ))}
      </div>

      {editing && (
        <>
          {profile.favourites.length > 0 && (
            <div className="marks">
              {profile.favourites.map((film) => (
                <button
                  className="mark"
                  key={film.id}
                  disabled={busy}
                  onClick={() =>
                    saveFavourites(profile.favourites.filter((item) => item.id !== film.id))
                  }
                >
                  ✕ {film.title_ru}
                </button>
              ))}
            </div>
          )}

          {profile.favourites.length >= MAX_FAVOURITES ? (
            <p className="hint">
              Больше {MAX_FAVOURITES} не помещается — уберите один, чтобы добавить другой.
            </p>
          ) : (
            <>
              <input
                className="field"
                value={query}
                placeholder="Найти фильм"
                onChange={(event) => setQuery(event.target.value)}
              />
              {found.map((film) => (
                <button
                  className="slot-row"
                  key={film.id}
                  disabled={busy}
                  onClick={() => saveFavourites([...profile.favourites, film])}
                >
                  <div>
                    <p className="film-row__title">{film.title_ru}</p>
                    <p className="meta">{film.year}</p>
                  </div>
                  <span />
                </button>
              ))}
            </>
          )}
        </>
      )}

      {profile.recent.length > 0 && (
        <>
          <h3>Недавнее</h3>
          {profile.recent.map((item, index) => (
            <div className="film-row film-row--clickable" key={index} onClick={() => openFilm({
              id: item.film_id,
              tmdb_id: null,
              title_ru: item.film_title,
              title_orig: null,
              year: item.film_year,
              poster_url: item.film_poster,
              genres: [],
              directors: [],
              in_catalog: true,
              my_interests: [],
              can_renew_soon: false,
              soon_expires_at: null,
              watched: false,
            })}>
              <Poster url={item.film_poster} />
              <div>
                <p className="film-row__title">{item.film_title}</p>
                <p className="meta">
                  {ACTION[item.kind] ?? item.kind}
                  {item.rating !== null && ` · ${item.rating.toFixed(1)} ★`}
                </p>
                {item.text && <p className="meta">{item.text}</p>}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

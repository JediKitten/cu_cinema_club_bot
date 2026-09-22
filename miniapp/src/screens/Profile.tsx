import { useEffect, useState } from "react";
import { addFriend, getProfile, removeFriend, searchFilms, setFavourites } from "../api";
import { Achievements } from "../components/Achievements";
import { BackLink } from "../components/BackLink";
import { Bars } from "../components/Bars";
import { dayLabel } from "../dates";
import { Poster } from "../components/FilmRow";
import { useOpenFilm } from "../filmOpener";
import { haptic, showMessage, bindBackButton } from "../telegram";
import { plural } from "../plural";
import { ROLE_LABEL } from "../roles";
import type { FilmBrief } from "../types";
import type { ProfileDoor } from "./ProfileTab";
import { useLoad, useSearch } from "../useLoad";

const MAX_FAVOURITES = 4;

/** Плитка с числом: три в ряд, без перехода куда-либо. */
function Tile({ value, label }: { value: number; label: string }) {
  return (
    <div className="stat">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

/** Строка статистики. С обработчиком — кнопка, ведущая в свой список.
 *
 * Одна и та же строка в обеих ролях: иначе в чужом профиле числа стояли бы
 * на пиксель иначе, чем в своём, и это было бы заметно.
 */
function Stat({
  value,
  label,
  onOpen,
}: {
  value: number;
  label: string;
  onOpen?: (() => void) | undefined;
}) {
  const content = (
    <>
      <b>{value}</b>
      <span>{label}</span>
      {onOpen && <span className="stat-row__arrow">›</span>}
    </>
  );
  return onOpen ? (
    <button className="stat-row stat-row--door" onClick={onOpen}>
      {content}
    </button>
  ) : (
    <div className="stat-row">{content}</div>
  );
}

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
  onOpenDoor,
  onOpenMenu,
}: {
  userId: number;
  /** Экран остаётся смонтированным под карточкой фильма — но кнопка «назад»
   *  в это время принадлежит карточке, а не ему. */
  active?: boolean;
  /** Нет, когда профиль открыт вкладкой: возвращаться оттуда некуда. */
  onBack?(): void;
  /** Только в своём профиле: строки статистики открывают свои списки. */
  onOpenDoor?(door: ProfileDoor): void;
  /** Иконка меню в углу. Вкладка «Ещё» уехала сюда, чтобы внизу осталось
   *  четыре вкладки, а не пять. */
  onOpenMenu?(): void;
}) {
  const { data: profile, setData: setProfile, error } = useLoad(() => getProfile(userId), [userId]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState("");
  const openFilm = useOpenFilm();

  useEffect(
    // Кнопку «назад» показываем, только когда есть куда возвращаться.
    () => bindBackButton(active && onBack !== undefined, onBack ?? (() => {})),
    [active, onBack],
  );

  // Ничего не отсеиваем: фильм из TMDB тоже годится в любимые, в каталог
  // он попадёт в момент выбора.
  const { found } = useSearch(
    query,
    async (text) => (await searchFilms(text)).slice(0, 6),
    { delay: 350, enabled: editing },
  );

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
      const saved = await setFavourites(films);
      setProfile({ ...profile, favourites: saved });
      setQuery("");
    } catch (e) {
      showMessage(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  if (error)
    return (
      <div className="screen">
        {onBack && <BackLink onBack={onBack} />}
        <div className="error">{error}</div>
      </div>
    );
  if (!profile) return <div className="center">Загрузка…</div>;

  // Двери открываются только в своём профиле — и только если есть куда вести.
  const door = profile.is_me ? onOpenDoor : undefined;

  const relation = profile.relation_friends
    ? "в друзьях"
    : profile.relation_following
      ? "вы подписаны"
      : profile.relation_follower
        ? "подписан на вас"
        : null;

  return (
    <div className="screen">
      {/* В браузере и старых клиентах родной кнопки «назад» нет, а профиль
          открыт окном поверх вкладки — выйти было бы нечем. */}
      {onBack && <BackLink onBack={onBack} />}
      <div className="profile__head">
        <Avatar url={profile.photo_url} name={profile.display_name} size={64} />
        <div className="profile__who">
          <h1 style={{ fontSize: 20, margin: 0 }}>{profile.display_name}</h1>
          {profile.tg_username && <p className="meta">@{profile.tg_username}</p>}
          <p className="meta">
            {ROLE_LABEL[profile.role]}
            {relation && ` · ${relation}`}
          </p>
        </div>
        {onOpenMenu && (
          <button className="icon-button" onClick={onOpenMenu} aria-label="Меню">
            ☰
          </button>
        )}
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

      {/* Слева три числа — сколько хочет посмотреть, сколько посмотрел, сколько
          друзей; справа распределение оценок. Рядом, а не друг под другом:
          оба блока про одно и то же — что это за зритель, — и вместе читаются
          одним взглядом.
          В своём профиле каждая строка — вход в свой список. В чужом это просто
          числа: поимённый список желаемого публичным быть не должен (§11). */}
      <div className={`profile__top ${profile.ratings > 0 ? "" : "profile__top--alone"}`}>
        <div className="stat-rows">
          <Stat
            value={profile.marks}
            label={plural(profile.marks, ["отметка", "отметки", "отметок"])}
            onOpen={door && (() => door("marks"))}
          />
          <Stat
            value={profile.watched}
            label="просмотрено"
            onOpen={door && (() => door("watched"))}
          />
          <Stat
            value={profile.friends}
            label={plural(profile.friends, ["друг", "друга", "друзей"])}
            onOpen={door && (() => door("friends"))}
          />
        </div>

        {profile.ratings > 0 && (
          <div className="profile__ratings">
            <div className="profile__row">
              <h3 style={{ margin: 0, fontSize: 15 }}>Как оценивает</h3>
              <span className="hint">{profile.ratings}</span>
            </div>
            <Bars
              compact
              data={profile.ratings_by_score.map((count, index) => ({
                // Подпись только у краёв: в половину ширины десять не влезают,
                // а «от половины звезды до пяти» понятно и по двум.
                label: String((index + 1) / 2).replace(".", ","),
                value: count,
              }))}
              color="var(--soon)"
            />
            <p className="hint">
              Средняя — {profile.average_rating?.toFixed(1).replace(".", ",") ?? "—"} из 5
            </p>
          </div>
        )}
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
                  key={film.id ?? `tmdb-${film.tmdb_id}`}
                  disabled={busy}
                  onClick={() => saveFavourites([...profile.favourites, film])}
                >
                  <div>
                    <p className="film-row__title">{film.title_ru}</p>
                    <p className="meta">
                      {film.year}
                      {/* Фильма ещё нет в каталоге — он заведётся при выборе. */}
                      {film.id === null && " · найдено в TMDB"}
                    </p>
                  </div>
                  <span />
                </button>
              ))}
            </>
          )}
        </>
      )}

      <Achievements data={profile.achievements} isMe={profile.is_me} />

      {/* Посещаемость — под витриной любимого: это тоже про человека, но уже
          не про вкус, а про то, доходит ли он до зала. */}
      {profile.attendance.came + profile.attendance.planned > 0 && (
        <>
          <div className="profile__row">
            <h3 style={{ margin: 0 }}>Ходит в клуб</h3>
            {profile.attendance.ratio !== null && (
              <span className="hint">
                дошёл {Math.round(profile.attendance.ratio * 100)}%
              </span>
            )}
          </div>
          {/* Здесь плитки, а не строки: числа равнозначны и читаются в ряд,
              а кликать в них некуда. */}
          <div className="stats-grid stats-grid--three">
            <Tile value={profile.attendance.came} label="был на показах" />
            <Tile value={profile.attendance.planned} label="собирался" />
            <Tile
              value={Math.max(profile.attendance.planned - profile.attendance.came, 0)}
              label="не дошёл"
            />
          </div>
          {profile.attendance.last_film && (
            <p className="hint">
              Последний раз: {profile.attendance.last_film}
              {profile.attendance.last_at && ` · ${dayLabel(profile.attendance.last_at)}`}
            </p>
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

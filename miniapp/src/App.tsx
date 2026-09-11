import { useCallback, useEffect, useState } from "react";
import { login } from "./api";
import { Catalog } from "./screens/Catalog";
import { Deck } from "./screens/Deck";
import { FilmDetail } from "./screens/FilmDetail";
import { Gate } from "./screens/Gate";
import { Profile } from "./screens/Profile";
import { ProfileTab } from "./screens/ProfileTab";
import { Tournament } from "./screens/Tournament";
import { Week } from "./screens/Week";
import { FilmOpenerProvider } from "./filmOpener";
import { initTelegram } from "./telegram";
import type { FilmBrief, User } from "./types";

type Tab = "catalog" | "deck" | "vote" | "profile";

// Четыре вкладки у всех одинаковые. «Ещё» уехало под иконку в углу профиля,
// «Клуб», «Мои» и «Друзья» — двери оттуда же: вкладки, которые у разных людей
// разные, сбивают с толку, а пятая кнопка внизу делала панель тесной.
const TABS: { key: Tab; icon: string; label: string }[] = [
  { key: "catalog", icon: "🎞", label: "Каталог" },
  { key: "deck", icon: "🔥", label: "Лента" },
  { key: "vote", icon: "📅", label: "Расписание" },
  { key: "profile", icon: "👤", label: "Профиль" },
];

// Статистика по фильму — админам и главному: модератор ведёт показы, а не отбор.
const STATS_ROLES = new Set(["admin", "superadmin"]);

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("catalog");
  // Фильм из поиска ещё не в каталоге — у него есть только tmdb_id.
  const [openFilm, setOpenFilm] = useState<FilmBrief | null>(null);
  // Профиль открывается поверх вкладок — как карточка фильма.
  const [openProfile, setOpenProfile] = useState<number | null>(null);
  // Турнир — тоже наложение: в него заходят из плашки в каталоге или
  // расписании и возвращаются туда же.
  const [openTournament, setOpenTournament] = useState<number | null>(null);

  // Постоянные обработчики: подписка на кнопку «назад» Telegram живёт в эффекте
  // с ними в зависимостях, и новая функция на каждый рендер App заставляла её
  // сниматься и вешаться заново — при каждом переключении вкладки.
  const closeFilm = useCallback(() => setOpenFilm(null), []);
  const closeProfile = useCallback(() => setOpenProfile(null), []);
  const closeTournament = useCallback(() => setOpenTournament(null), []);

  // Бот открывает приложение адресом вида ?film=123 — сразу показываем карточку.
  useEffect(() => {
    const requested = new URLSearchParams(location.search).get("film");
    if (requested && /^\d+$/.test(requested)) {
      setOpenFilm({
        id: Number(requested),
        tmdb_id: null,
        title_ru: "",
        title_orig: null,
        year: null,
        poster_url: null,
        genres: [],
        directors: [],
        in_catalog: true,
        my_interests: [],
        can_renew_soon: false,
        soon_expires_at: null,
        watched: false,
      });
    }
  }, []);

  useEffect(() => {
    initTelegram();
    login()
      .then(setUser)
      .catch((e) =>
        setAuthError(e instanceof Error ? e.message : "Не удалось войти"),
      );
  }, []);

  if (authError) {
    return (
      <div className="center">
        <p>{authError}</p>
        <p className="hint">
          Приложение работает только внутри Telegram: вход подтверждается
          подписью, которую выдаёт сам мессенджер.
        </p>
      </div>
    );
  }

  if (!user) return <div className="center">Входим…</div>;

  // Закрытая бета: без кода внутрь не пускают. Проверяет всё равно сервер —
  // здесь мы только показываем, куда его вводить.
  if (!user.access) {
    return <Gate onOpen={() => setUser({ ...user, access: true })} />;
  }

  function open(film: FilmBrief) {
    if (film.id !== null || film.tmdb_id !== null) setOpenFilm(film);
  }

  return (
    <FilmOpenerProvider value={open}>
      <div className="app">
        {/* Вкладка остаётся смонтированной под карточкой: иначе возврат из фильма
          терял бы поисковый запрос, выдачу и место прокрутки. */}
        {tab === "catalog" && <Catalog onOpen={open} onOpenTournament={setOpenTournament} />}
        {tab === "deck" && <Deck onOpen={open} />}
        {tab === "vote" && <Week onOpenTournament={setOpenTournament} />}
        {tab === "profile" && (
          <ProfileTab me={user} onOpenFilm={open} onOpenProfile={setOpenProfile} />
        )}

        {/* Экраны не размонтируются под тем, что открылось поверх: вернувшись
            из карточки фильма, человек должен оказаться там же, где был. */}
        {openProfile !== null && (
          <div className="overlay" hidden={openFilm !== null}>
            <Profile
              userId={openProfile}
              active={openFilm === null}
              onBack={closeProfile}
            />
          </div>
        )}

        {openTournament !== null && openFilm === null && (
          <div className="overlay">
            <Tournament id={openTournament} onBack={closeTournament} />
          </div>
        )}

        {openFilm !== null && (
          // Карточка накрывает список, а не заменяет его: список под ней жив
          // и вернётся ровно таким, каким был.
          <div className="overlay">
            <FilmDetail
              filmId={openFilm.id}
              tmdbId={openFilm.tmdb_id}
              withStats={STATS_ROLES.has(user.role)}
              onBack={closeFilm}
            />
          </div>
        )}

        {/* Таб-бар прячем в карточке: там навигация — родная кнопка «назад» Telegram. */}
        {openFilm === null && openProfile === null && openTournament === null && (
          <nav className="tabs">
            {TABS.map((item) => (
              <button
                key={item.key}
                className={tab === item.key ? "is-active" : ""}
                onClick={() => setTab(item.key)}
              >
                <span className="tab-icon">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>
        )}
      </div>
    </FilmOpenerProvider>
  );
}

import { useEffect, useState } from "react";
import { login } from "./api";
import { Admin } from "./screens/Admin";
import { Catalog } from "./screens/Catalog";
import { FilmDetail } from "./screens/FilmDetail";
import { Gate } from "./screens/Gate";
import { More } from "./screens/More";
import { Week } from "./screens/Week";
import { MyList } from "./screens/MyList";
import { FilmOpenerProvider } from "./filmOpener";
import { initTelegram } from "./telegram";
import type { FilmBrief, User } from "./types";

type Tab = "catalog" | "mine" | "vote" | "admin" | "more";

const TABS: { key: Tab; icon: string; label: string }[] = [
  { key: "catalog", icon: "🎞", label: "Каталог" },
  { key: "mine", icon: "★", label: "Мои" },
  { key: "vote", icon: "📅", label: "Расписание" },
  { key: "admin", icon: "⚙", label: "Клуб" },
  { key: "more", icon: "☰", label: "Ещё" },
];

// Вкладка админки видна только тем, кто может ей пользоваться. Это удобство,
// а не защита: права проверяет бэкенд на каждом запросе.
const ADMIN_ROLES = new Set(["moderator", "admin", "superadmin"]);

// Статистика по фильму — админам и главному: модератор ведёт показы, а не отбор.
const STATS_ROLES = new Set(["admin", "superadmin"]);

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("catalog");
  // Фильм из поиска ещё не в каталоге — у него есть только tmdb_id.
  const [openFilm, setOpenFilm] = useState<FilmBrief | null>(null);

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
        {tab === "catalog" && <Catalog onOpen={open} />}
        {tab === "mine" && <MyList onOpen={open} />}
        {tab === "vote" && <Week />}
        {tab === "admin" && <Admin me={user} />}
        {tab === "more" && <More user={user} />}

        {openFilm !== null && (
          // Карточка накрывает список, а не заменяет его: список под ней жив
          // и вернётся ровно таким, каким был.
          <div className="overlay">
            <FilmDetail
              filmId={openFilm.id}
              tmdbId={openFilm.tmdb_id}
              withStats={STATS_ROLES.has(user.role)}
              onBack={() => setOpenFilm(null)}
            />
          </div>
        )}

        {/* Таб-бар прячем в карточке: там навигация — родная кнопка «назад» Telegram. */}
        {openFilm === null && (
          <nav className="tabs">
            {TABS.filter(
              (item) => item.key !== "admin" || ADMIN_ROLES.has(user.role),
            ).map((item) => (
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

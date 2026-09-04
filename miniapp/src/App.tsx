import { useEffect, useState } from "react";
import { login } from "./api";
import { Catalog } from "./screens/Catalog";
import { FilmDetail } from "./screens/FilmDetail";
import { More } from "./screens/More";
import { MyList } from "./screens/MyList";
import { initTelegram } from "./telegram";
import type { FilmBrief, User } from "./types";

type Tab = "catalog" | "mine" | "more";

const TABS: { key: Tab; icon: string; label: string }[] = [
  { key: "catalog", icon: "🎞", label: "Каталог" },
  { key: "mine", icon: "★", label: "Мои" },
  { key: "more", icon: "☰", label: "Ещё" },
];

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("catalog");
  const [openFilmId, setOpenFilmId] = useState<number | null>(null);

  useEffect(() => {
    initTelegram();
    login()
      .then(setUser)
      .catch((e) => setAuthError(e instanceof Error ? e.message : "Не удалось войти"));
  }, []);

  if (authError) {
    return (
      <div className="center">
        <p>{authError}</p>
        <p className="hint">
          Приложение работает только внутри Telegram: вход подтверждается подписью,
          которую выдаёт сам мессенджер.
        </p>
      </div>
    );
  }

  if (!user) return <div className="center">Входим…</div>;

  function openFilm(film: FilmBrief) {
    if (film.id) setOpenFilmId(film.id);
  }

  return (
    <div className="app">
      {openFilmId !== null ? (
        <FilmDetail filmId={openFilmId} onBack={() => setOpenFilmId(null)} />
      ) : (
        <>
          {tab === "catalog" && <Catalog onOpen={openFilm} />}
          {tab === "mine" && <MyList onOpen={openFilm} />}
          {tab === "more" && <More user={user} />}
        </>
      )}

      {/* Таб-бар прячем в карточке: там навигация — родная кнопка «назад» Telegram. */}
      {openFilmId === null && (
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
  );
}

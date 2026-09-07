import { useState } from "react";
import { Friends } from "./Friends";
import { MyList } from "./MyList";
import { Profile } from "./Profile";
import type { FilmBrief, User } from "../types";

type Sub = "mine" | "friends";

/** Вкладка «Профиль»: свой профиль и два входа — в свои фильмы и к людям.
 *
 * Списки и друзья остались отдельными экранами, но перестали занимать места
 * в панели вкладок: обе двери ведут отсюда, и обе — про вас.
 */
export function ProfileTab({
  me,
  onOpenFilm,
  onOpenProfile,
}: {
  me: User;
  onOpenFilm(film: FilmBrief): void;
  onOpenProfile(userId: number): void;
}) {
  const [sub, setSub] = useState<Sub | null>(null);

  if (sub !== null) {
    return (
      <>
        <div className="screen" style={{ paddingBottom: 0 }}>
          <button
            className="mark"
            style={{ alignSelf: "flex-start" }}
            onClick={() => setSub(null)}
          >
            ← Профиль
          </button>
        </div>
        {sub === "mine" ? (
          <MyList onOpen={onOpenFilm} />
        ) : (
          <Friends me={me} onOpenProfile={onOpenProfile} />
        )}
      </>
    );
  }

  return (
    <>
      <div className="screen" style={{ paddingBottom: 0 }}>
        <div className="profile__doors">
          <button className="primary" onClick={() => setSub("mine")}>
            ★ Мои фильмы
          </button>
          <button className="primary" onClick={() => setSub("friends")}>
            👥 Друзья
          </button>
        </div>
      </div>
      {/* Профиль здесь — вкладка, а не окно поверх: своей кнопки «назад» ему
          не нужно, её место занимает панель вкладок. */}
      <Profile userId={me.id} />
    </>
  );
}

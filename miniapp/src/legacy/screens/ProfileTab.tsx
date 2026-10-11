import { useState } from "react";
import { Friends } from "./Friends";
import { More } from "./More";
import { MyMarks, MyWatched } from "./MyList";
import { Profile } from "./Profile";
import type { FilmBrief, User } from "../types";

/** Куда ведут строки статистики и иконка меню в своём профиле. */
export type ProfileDoor = "marks" | "watched" | "friends" | "more";

const TITLE: Record<ProfileDoor, string> = {
  marks: "Отмеченное",
  watched: "Просмотренное",
  friends: "Друзья",
  more: "Ещё",
};

/** Вкладка «Профиль»: свой профиль и двери из него.
 *
 * Отдельных кнопок сверху нет: числа «отметок», «просмотрено» и «друзей» —
 * они и есть входы. Кнопка, дублирующая число, стоящее рядом, — лишняя.
 * «Ещё» живёт под иконкой в углу: внизу от этого остаётся четыре вкладки,
 * а не пять.
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
  const [door, setDoor] = useState<ProfileDoor | null>(null);

  if (door !== null) {
    return (
      <>
        <div className="screen" style={{ paddingBottom: 0 }}>
          <button
            className="mark"
            style={{ alignSelf: "flex-start" }}
            onClick={() => setDoor(null)}
          >
            ← Профиль
          </button>
          <h1 style={{ fontSize: 20, margin: 0 }}>{TITLE[door]}</h1>
        </div>
        {door === "marks" && <MyMarks onOpen={onOpenFilm} />}
        {door === "watched" && <MyWatched onOpen={onOpenFilm} />}
        {door === "friends" && <Friends onOpenProfile={onOpenProfile} />}
        {door === "more" && <More user={me} />}
      </>
    );
  }

  // Профиль здесь — вкладка, а не окно поверх: своей кнопки «назад» ему
  // не нужно, её место занимает панель вкладок.
  return <Profile userId={me.id} onOpenDoor={setDoor} onOpenMenu={() => setDoor("more")} />;
}

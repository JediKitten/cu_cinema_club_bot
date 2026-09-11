import { useState } from "react";
import { Trophy } from "./Trophy";
import type { Achievements as Data, AchievementTier } from "../types";

const ORDER: AchievementTier[] = ["bronze", "silver", "gold", "platinum"];

const plural = (count: number) =>
  count % 10 === 1 && count % 100 !== 11
    ? "секретная ачивка"
    : [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)
      ? "секретные ачивки"
      : "секретных ачивок";

/** Ачивки: четыре трофея с числами, за ними — разбор по целям.
 *
 * Человек держит одну ачивку на цель — высшую достигнутую, — поэтому числа
 * считают цели, а не награды: список из двадцати строк, где девятнадцать
 * перечёркнуты, никому не нужен.
 *
 * Секретные до получения не показываются вовсе: ни названия, ни условия,
 * только счётчик. Найти их должно быть сюрпризом.
 */
export function Achievements({ data, isMe }: { data: Data; isMe: boolean }) {
  const [open, setOpen] = useState(false);
  const total = data.bronze + data.silver + data.gold + data.platinum;

  return (
    <>
      <div className="profile__row">
        <h3 style={{ margin: 0 }}>Ачивки</h3>
        {total > 0 && <span className="hint">всего {total}</span>}
      </div>

      {/* Сам блок и есть переключатель: отдельная кнопка «Подробнее» рядом
          с четырьмя трофеями — вторая вещь, на которую надо нажать, чтобы
          сделать одно и то же. */}
      <button
        className={`trophies ${open ? "is-open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {ORDER.map((tier) => (
          <span className={`trophy ${data[tier] > 0 ? "is-on" : ""}`} key={tier}>
            {/* Пустой уровень — тот же трофей, но приглушённый: видно, что он
                есть и его можно взять. */}
            <Trophy tier={tier} size={26} muted={data[tier] === 0} />
            <b>{data[tier]}</b>
          </span>
        ))}
      </button>

      {total === 0 && !open && (
        <p className="hint">
          {isMe
            ? "Пока ни одной. Отметьте фильм просмотренным, поставьте оценку или придите на показ."
            : "Пока ни одной."}
        </p>
      )}

      {open && (
        <>
          {data.groups.map((item) => (
            <div className={`achievement ${item.tier ? "is-earned" : ""}`} key={item.group}>
              <span className="achievement__emoji">
                {item.tier ? (
                  <Trophy tier={item.tier} size={28} />
                ) : (
                  // Ещё не взято — показываем трофей той ступени, к которой идёт.
                  <Trophy tier={item.next_tier ?? "bronze"} size={28} muted />
                )}
              </span>
              <span className="achievement__text">
                <b>{item.tier ? item.title : item.label}</b>
                <span className="meta">{item.tier ? item.description : item.next_title}</span>
                {/* Прогресс — к следующей ступени. У платины расти некуда. */}
                {item.target > 0 && (
                  <span className="meta">
                    {item.tier ? "дальше: " : ""}
                    {item.next_title && item.tier ? `${item.next_title} — ` : ""}
                    {item.progress} из {item.target}
                  </span>
                )}
              </span>
              {item.tier && <span className="achievement__check">✓</span>}
            </div>
          ))}

          {data.secrets_left > 0 && (
            <div className="achievement achievement--secret">
              <span className="achievement__emoji">❓</span>
              <span className="achievement__text">
                <b>
                  Осталось {data.secrets_left} {plural(data.secrets_left)}
                </b>
                <span className="meta">Условия не подскажем — в этом и смысл.</span>
              </span>
            </div>
          )}
        </>
      )}
    </>
  );
}

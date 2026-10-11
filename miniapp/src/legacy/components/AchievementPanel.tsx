import { useEffect, useState } from "react";
import {
  ApiError,
  findUsers,
  grantAchievement,
  listCustomAchievements,
  revokeAchievement,
} from "../api";
import { Trophy } from "./Trophy";
import { haptic, showMessage } from "../telegram";
import type { AchievementTier, CustomAchievement, TeamMember } from "../types";

const TIERS: { key: AchievementTier; label: string }[] = [
  { key: "bronze", label: "Бронза" },
  { key: "silver", label: "Серебро" },
  { key: "gold", label: "Золото" },
  { key: "platinum", label: "Платина" },
];

/** Именные ачивки: придумать на месте и выдать конкретному человеку.
 *
 * В реестре кода такому места нет — «за то, что притащил проектор» бывает
 * один раз и ни у кого больше. Поэтому текст задаётся здесь и живёт в самой
 * записи; в профиле она считается наравне с заслуженными автоматом.
 */
export function AchievementPanel() {
  const [given, setGiven] = useState<CustomAchievement[]>([]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<TeamMember[]>([]);
  const [person, setPerson] = useState<TeamMember | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tier, setTier] = useState<AchievementTier>("gold");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCustomAchievements().then(setGiven).catch(() => {});
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (person !== null || trimmed.length < 2) {
      setFound([]);
      return;
    }
    let alive = true;
    const timer = setTimeout(() => {
      findUsers(trimmed)
        .then((people) => alive && setFound(people.slice(0, 5)))
        .catch(() => alive && setFound([]));
    }, 350);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [query, person]);

  async function guard(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      haptic();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Не получилось";
      setError(message);
      showMessage(message);
    } finally {
      setBusy(false);
    }
  }

  const give = () =>
    guard(async () => {
      if (person === null) return;
      await grantAchievement(person.id, title.trim(), description.trim(), tier);
      setGiven(await listCustomAchievements());
      setPerson(null);
      setQuery("");
      setTitle("");
      setDescription("");
    });

  const take = (id: number) =>
    guard(async () => {
      await revokeAchievement(id);
      setGiven(await listCustomAchievements());
    });

  return (
    <>
      {error && <div className="error">{error}</div>}

      <h3>Именная ачивка</h3>
      <p className="hint">
        Для того, чего нет в общем списке и не будет: «спас показ», «притащил проектор».
        Человек получит уведомление, а трофей встанет в его профиль наравне с остальными.
      </p>

      {person === null ? (
        <>
          <input
            className="field"
            value={query}
            placeholder="Найти участника по имени или @username"
            onChange={(event) => setQuery(event.target.value)}
          />
          {found.map((item) => (
            <button
              className="slot-row"
              key={item.id}
              disabled={busy}
              onClick={() => {
                setPerson(item);
                setQuery(item.display_name);
              }}
            >
              <span>
                {item.display_name}
                {item.tg_username && <span className="meta"> · @{item.tg_username}</span>}
              </span>
              <span className="hint">→</span>
            </button>
          ))}
        </>
      ) : (
        <>
          <div className="slot-row">
            <span className="film-row__title">{person.display_name}</span>
            <button className="mark" onClick={() => setPerson(null)}>
              Другой
            </button>
          </div>

          <input
            className="field"
            value={title}
            placeholder="Название — «Спас показ»"
            maxLength={120}
            onChange={(event) => setTitle(event.target.value)}
          />
          <input
            className="field"
            value={description}
            placeholder="За что — «Притащил проектор из дома»"
            maxLength={200}
            onChange={(event) => setDescription(event.target.value)}
          />

          <div className="marks">
            {TIERS.map((item) => (
              <button
                className={`mark ${tier === item.key ? "is-on mark--wishlist" : ""}`}
                key={item.key}
                onClick={() => setTier(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <button className="primary" disabled={busy || !title.trim()} onClick={() => void give()}>
            Выдать
          </button>
        </>
      )}

      {given.length > 0 && (
        <>
          <h3>Уже выдано</h3>
          {given.map((item) => (
            <div className="achievement is-earned" key={item.id}>
              <span className="achievement__emoji">
                <Trophy tier={item.tier} size={28} />
              </span>
              <span className="achievement__text">
                <b>{item.title}</b>
                <span className="meta">{item.user_name}</span>
                {item.description && <span className="meta">{item.description}</span>}
              </span>
              <button className="mark" disabled={busy} onClick={() => void take(item.id)}>
                Снять
              </button>
            </div>
          ))}
        </>
      )}
    </>
  );
}

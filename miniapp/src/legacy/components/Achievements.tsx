import { useState } from "react";
import { Trophy } from "./Trophy";
import type { Achievements as Data, AchievementStep, AchievementTier } from "../types";

const ORDER: AchievementTier[] = ["bronze", "silver", "gold", "platinum"];

const TIER_NAME: Record<AchievementTier, string> = {
  bronze: "Бронзовые",
  silver: "Серебряные",
  gold: "Золотые",
  platinum: "Платиновые",
};

function secretsLine(count: number): string {
  const one = count % 10 === 1 && count % 100 !== 11;
  const few = [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100);
  return `Осталось ${count} ${one ? "секретная" : few ? "секретные" : "секретных"} ${
    one ? "ачивка" : few ? "ачивки" : "ачивок"
  }`;
}

/** Ступень: полученная — ярко и с галочкой, будущая — бледно и с прогрессом.
 *
 * У неполученной сервер не присылает названия: как её назовут, приятнее
 * узнать в момент выдачи. Подписью строки становится само условие — знать,
 * что делать, человек должен, и строка без заголовка выглядела бы поломкой.
 *
 * `hidden` — чужая секретная, которую вы сами не открыли: трофей показываем,
 * название и условие нет. Прогресс у неё тоже не рисуем: «1 из 1» ничего
 * не сообщает, кроме того, что она взята, а это и так видно по галочке.
 */
function Row({ step, hidden = false }: { step: AchievementStep; hidden?: boolean }) {
  const earned = step.earned_at !== null;
  return (
    <div className={`achievement ${earned ? "is-earned" : ""}`}>
      <span className="achievement__emoji">
        <Trophy tier={step.tier} size={28} muted={!earned} />
      </span>
      <span className="achievement__text">
        <b>{hidden ? "🔒 Секретное достижение" : step.title || step.description}</b>
        {(hidden || step.title) && <span className="meta">{step.description}</span>}
        {!earned && !hidden && (
          <span className="meta">
            {step.progress} из {step.target}
          </span>
        )}
      </span>
      {earned && <span className="achievement__check">✓</span>}
    </div>
  );
}

/** Ачивки: четыре трофея с числами, каждый — вкладка своей редкости.
 *
 * Числа считают все взятые ступени: взял серебро — бронза той же цели
 * остаётся полученной и продолжает гореть. Во вкладке уровня стоит и то,
 * что на нём уже взято, и то, что на нём же ещё можно взять: список одних
 * наград не отвечает на единственный интересный вопрос — что дальше.
 *
 * Названия неполученных скрыты, условия — нет. Секретные до получения
 * не показываются вовсе: ни названия, ни условия, только счётчик на своём
 * уровне. Найти их должно быть сюрпризом.
 */
export function Achievements({ data, isMe }: { data: Data; isMe: boolean }) {
  const [tab, setTab] = useState<AchievementTier | null>(null);
  const total = ORDER.reduce((sum, tier) => sum + data[tier], 0);

  // Все ступени этой редкости, в порядке целей из таблицы клуба. Показываем
  // и недостижимые пока: вкладка «золото» у новичка иначе выглядит пустой,
  // хотя посмотреть там есть на что.
  const steps = (tier: AchievementTier) =>
    data.groups.flatMap((item) =>
      item.steps.filter((step) => step.tier === tier).map((step) => ({ step, hidden: item.hidden })),
    );

  return (
    <>
      <div className="profile__row">
        <h3 style={{ margin: 0 }}>Ачивки</h3>
        {total > 0 && <span className="hint">всего {total}</span>}
      </div>

      {/* Трофеи и есть вкладки: нажатие открывает свою редкость, повторное —
          закрывает. Отдельная кнопка «Подробнее» рядом с ними была бы второй
          вещью, на которую надо нажать ради того же самого. */}
      <div className="trophies" role="tablist">
        {ORDER.map((tier) => (
          <button
            className={`trophy ${data[tier] > 0 ? "is-on" : ""} ${tab === tier ? "is-open" : ""}`}
            key={tier}
            role="tab"
            aria-selected={tab === tier}
            onClick={() => setTab((current) => (current === tier ? null : tier))}
          >
            {/* Пустой уровень — тот же трофей, но приглушённый: видно, что он
                есть и его можно взять. */}
            <Trophy tier={tier} size={26} muted={data[tier] === 0} />
            <b>{data[tier]}</b>
          </button>
        ))}
      </div>

      {tab === null && total === 0 && (
        <p className="hint">
          {isMe
            ? "Пока ни одной. Отметьте фильм просмотренным, поставьте оценку или придите на показ."
            : "Пока ни одной."}
        </p>
      )}

      {tab !== null && (
        <>
          <div className="profile__row">
            <h4 className="achievements__title">{TIER_NAME[tab]}</h4>
            <span className="hint">
              {data[tab]} из {steps(tab).length + (data.secrets_left[tab] ?? 0)}
            </span>
          </div>

          {steps(tab).map(({ step, hidden }, index) => (
            <Row key={`${step.description}-${index}`} step={step} hidden={hidden} />
          ))}

          {(data.secrets_left[tab] ?? 0) > 0 && (
            <div className="achievement achievement--secret">
              <span className="achievement__emoji">❓</span>
              <span className="achievement__text">
                <b>{secretsLine(data.secrets_left[tab] ?? 0)}</b>
                <span className="meta">Условия не подскажем — в этом и смысл.</span>
              </span>
            </div>
          )}

          {steps(tab).length === 0 && !(data.secrets_left[tab] ?? 0) && (
            <p className="hint">На этом уровне ачивок нет.</p>
          )}
        </>
      )}
    </>
  );
}

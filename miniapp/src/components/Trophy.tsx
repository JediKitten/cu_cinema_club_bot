import type { AchievementTier } from "../types";

/** Трофеи уровней — рисованные, а не картинками.
 *
 * SVG, а не файлы: четыре иконки в трёх размерах стоили бы лишних запросов
 * и мутных краёв на плотных экранах, а так они ещё и красятся под тему.
 * Внутри чаши «плей» — клуб про кино, и это единственная деталь, которая
 * читается в 22 пикселя.
 *
 * Формы нарочно крупные и без мелкой лепки: всё тоньше двух пикселей на такой
 * иконке просто исчезает.
 */

type Props = { tier: AchievementTier; size?: number; muted?: boolean };

const METAL: Record<AchievementTier, [string, string, string]> = {
  // светлый блик, основной тон, тень
  bronze: ["#f0b489", "#c87b45", "#7d421d"],
  silver: ["#f4f7fa", "#c3ccd4", "#79838c"],
  gold: ["#ffe49a", "#f0b429", "#a9720c"],
  platinum: ["#ffffff", "#dfe7ee", "#8d99a6"],
};

export function Trophy({ tier, size = 22, muted = false }: Props) {
  const [light, base, shade] = METAL[tier];
  const id = `trophy-${tier}${muted ? "-off" : ""}`;
  // Пустой уровень видно, но хвастаться им нечем.
  const dim = muted ? { opacity: 0.35, filter: "grayscale(1)" } : undefined;

  return (
    <svg
      className="trophy-icon"
      width={size}
      height={size}
      viewBox="0 0 48 48"
      aria-hidden="true"
      style={dim}
    >
      <defs>
        <linearGradient id={`${id}-body`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={light} />
          <stop offset="45%" stopColor={base} />
          <stop offset="100%" stopColor={shade} />
        </linearGradient>
        <radialGradient id={`${id}-orb`} cx="0.35" cy="0.3" r="0.8">
          <stop offset="0%" stopColor="#9fe8ff" />
          <stop offset="55%" stopColor="#2f7fe0" />
          <stop offset="100%" stopColor="#12306b" />
        </radialGradient>
      </defs>

      {/* Подставка — общая у всех: разница между уровнями наверху, и глазу
          проще ловить её, когда низ одинаковый. */}
      <path d="M14 41h20a2 2 0 0 1 0 4H14a2 2 0 0 1 0-4Z" fill={`url(#${id}-body)`} />
      <path d="M18.5 35h11l1.8 6H16.7l1.8-6Z" fill={`url(#${id}-body)`} />
      <path d="M22.2 27h3.6v9h-3.6z" fill={`url(#${id}-body)`} />

      {tier === "platinum" ? (
        <>
          {/* Платина — не чаша, а сфера в раскрытых ладонях: её ни с чем
              не спутать даже в двадцать пикселей. Ручек нет: ладони и есть
              ручки, а третья пара форм по бокам превратила бы иконку в кашу. */}
          <path
            d="M22.5 30C15 26.5 10.5 18 12.5 8.5"
            fill="none"
            stroke={`url(#${id}-body)`}
            strokeWidth="4.6"
            strokeLinecap="round"
          />
          <path
            d="M25.5 30C33 26.5 37.5 18 35.5 8.5"
            fill="none"
            stroke={`url(#${id}-body)`}
            strokeWidth="4.6"
            strokeLinecap="round"
          />
          <circle cx="24" cy="17" r="9.5" fill={`url(#${id}-orb)`} />
          <ellipse cx="20.5" cy="13.5" rx="3.2" ry="2.2" fill="#ffffff" opacity="0.4" />
          <path d="M21.3 13.2v7.6L27.5 17l-6.2-3.8Z" fill="#ffffff" opacity="0.92" />
        </>
      ) : (
        <>
          {/* Ручки линией, а не фигурой: у залитой формы концы торчат хвостами
              из-под чаши, и на маленьком размере это первое, что бросается
              в глаза. */}
          <path
            d="M13.5 11H9.5A3.5 3.5 0 0 0 6 14.5V16c0 4.2 2.8 7.8 6.7 9"
            fill="none"
            stroke={`url(#${id}-body)`}
            strokeWidth="3.4"
            strokeLinecap="round"
          />
          <path
            d="M34.5 11h4a3.5 3.5 0 0 1 3.5 3.5V16c0 4.2-2.8 7.8-6.7 9"
            fill="none"
            stroke={`url(#${id}-body)`}
            strokeWidth="3.4"
            strokeLinecap="round"
          />
          {/* Ободок: без него чаша с прямым верхом читается ведром. */}
          <rect x="11.6" y="4" width="24.8" height="4" rx="1.6" fill={light} />
          <rect x="11.6" y="4" width="24.8" height="4" rx="1.6" fill={shade} opacity="0.18" />
          {/* Чаша: высокая и сужающаяся книзу — приземистая читается как миска. */}
          <path
            d="M13 8h22v6c0 7.6-4.6 13.4-11 15.5C17.6 27.4 13 21.6 13 14V8Z"
            fill={`url(#${id}-body)`}
          />
          {/* Киномотив внутри — «плей»: на 22 пикселях сложнее ничего не видно. */}
          <path d="M20.8 11.4v8.6l7.4-4.3-7.4-4.3Z" fill={light} opacity="0.85" />
          {/* Блик слева — он и делает металл металлом. */}
          <path
            d="M16 9h2.8v5.6c0 3.9 1 7 2.7 9.4C18 21.9 16 18.3 16 14.2V9Z"
            fill="#ffffff"
            opacity="0.22"
          />
        </>
      )}
    </svg>
  );
}

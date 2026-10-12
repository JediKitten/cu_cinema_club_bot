import { useId, type MouseEvent } from 'react'
import { Icon } from './Icon'
import { markButtons, nextMark } from '../lib/marks'
import { starFills } from '../lib/format'
import { haptic } from '../lib/tg'
import type { FilmShort, Mark } from '../lib/types'

/* ---------- Постер ---------- */

export function Poster({
  film,
  width,
  height,
  onClick,
}: {
  film: Pick<FilmShort, 'title' | 'originalTitle' | 'posterUrl'>
  width: number | string
  height?: number | string
  onClick?: () => void
}) {
  const style = { width, height: height ?? 'auto', aspectRatio: height ? undefined : '2 / 3' }
  const content = film.posterUrl ? <img src={film.posterUrl} alt="" loading="lazy" /> : film.originalTitle ?? film.title
  if (!onClick) return <div className="poster" style={style} aria-hidden="true">{content}</div>
  return (
    <button type="button" className="poster" style={style} onClick={onClick} aria-label={`${film.title} — карточка фильма`}>
      {content}
    </button>
  )
}

/* ---------- Отметки «Желаемое» / «Ближайшее» ---------- */

export function MarkButtons({
  mark,
  block = false,
  onChange,
}: {
  mark: Mark
  /** Растянуть кнопки на всю ширину (карточка фильма) */
  block?: boolean
  onChange: (next: Mark) => void
}) {
  const b = markButtons(mark)
  const press = (action: 'wish' | 'soon') => {
    haptic.select()
    onChange(nextMark(mark, action))
  }
  const btn = (kind: 'wish' | 'soon') => {
    const s = b[kind]
    return (
      <button
        key={kind}
        type="button"
        className={block ? 'mark mark--block' : 'mark'}
        data-variant={kind}
        aria-pressed={s.pressed}
        aria-label={s.renew ? 'Снова в ближайшее — ещё на 2 недели' : undefined}
        onClick={() => press(kind)}
      >
        {s.pressed ? (
          <CheckIcon />
        ) : s.renew ? (
          <Icon name="renew" size={14} strokeWidth={2} />
        ) : (
          <span className={`mark__dot mark__dot--${kind}`} />
        )}
        {s.label}
      </button>
    )
  }
  return <div className={block ? 'grid-2' : 'row'}>{btn('wish')}{btn('soon')}</div>
}

/** Галочка — одна на всё приложение: отметки, «Смотрел», «Приду», чекбоксы */
export function CheckIcon({ size = 14 }: { size?: number }) {
  return <Icon name="check" size={size} strokeWidth={2.4} />
}

/** Подпись-легенда к отметкам — объясняет главную механику клуба на месте. */
export function MarkLegend() {
  return (
    <div className="legend">
      <span><span className="mark__dot mark__dot--wish" />Желаемое — когда-нибудь</span>
      <span><span className="mark__dot mark__dot--soon" />Ближайшее — в 2 недели, вес ×3</span>
    </div>
  )
}

/* ---------- «Смотрел» ---------- */

export function SeenToggle({ seen, onChange, onPoster = false }: { seen: boolean; onChange: (v: boolean) => void; onPoster?: boolean }) {
  return (
    <button
      type="button"
      className={onPoster ? 'seen-toggle seen-toggle--poster' : 'seen-toggle'}
      aria-pressed={seen}
      onClick={() => {
        haptic.select()
        onChange(!seen)
      }}
    >
      {seen ? <CheckIcon /> : <Icon name="eye" size={14} strokeWidth={1.8} />}
      Смотрел
    </button>
  )
}

/* ---------- Строка фильма ---------- */

export function FilmRow({
  film,
  onOpen,
  onMark,
  onSeen,
}: {
  film: FilmShort & { mark: Mark; seen: boolean; fromTmdb?: boolean }
  onOpen: () => void
  onMark: (m: Mark) => void
  onSeen: (v: boolean) => void
}) {
  const directors = film.directors.length > 2 ? `${film.directors.slice(0, 2).join(', ')} и др.` : film.directors.join(', ')
  return (
    <div className="film-row">
      <Poster film={film} width={64} height={96} onClick={onOpen} />
      <div className="film-row__body">
        <div className="row row--between" style={{ alignItems: 'flex-start' }}>
          <button type="button" className="film-row__title" onClick={onOpen}>
            <span className="film-row__name">{film.title}</span>
            <span className="film-row__meta">{[film.year, film.originalTitle].filter(Boolean).join(' · ')}</span>
            {directors && <span className="film-row__meta">{directors}</span>}
            {film.fromTmdb && <span className="film-row__meta">Найдено в TMDB</span>}
          </button>
          <SeenToggle seen={film.seen} onChange={onSeen} />
        </div>
        <MarkButtons mark={film.mark} onChange={onMark} />
      </div>
    </div>
  )
}

/* ---------- Звёзды с половинками ---------- */

const STAR = 'M12 2.8l2.8 5.7 6.3.9-4.6 4.4 1.1 6.2L12 17l-5.6 3 1.1-6.2L2.9 9.4l6.3-.9z'

/**
 * Нажатие на левую половину звезды — «.5», на правую — целое.
 * Нажатие на текущее значение снимает оценку (onChange(undefined)).
 */
export function Stars({
  value,
  onChange,
  label,
  size = 'md',
}: {
  value: number | undefined
  onChange?: (v: number | undefined) => void
  label: string
  size?: 'sm' | 'md'
}) {
  const clipId = useId()
  const glyph = size === 'sm' ? 30 : 32
  const pick = (i: number) => (e: MouseEvent<HTMLButtonElement>) => {
    if (!onChange) return
    const rect = e.currentTarget.getBoundingClientRect()
    const isKeyboard = e.detail === 0
    const left = !isKeyboard && e.clientX - rect.left < rect.width / 2
    const v = left ? i - 0.5 : i
    haptic.select()
    onChange(v === value ? undefined : v)
  }
  return (
    <fieldset className={`stars${size === 'sm' ? ' stars--sm' : ''}`}>
      <legend className="sr-only">{label}</legend>
      {starFills(value).map((fill, idx) => (
        <button
          key={idx}
          type="button"
          className="stars__btn"
          aria-label={`${idx + 1} из 5`}
          aria-pressed={fill !== 'empty'}
          disabled={!onChange}
          onClick={pick(idx + 1)}
        >
          <svg width={glyph} height={glyph} viewBox="0 0 24 24" aria-hidden="true">
            <defs>
              <clipPath id={`${clipId}-${idx}`}>
                <rect x="0" y="0" width="12" height="24" />
              </clipPath>
            </defs>
            {fill === 'full' ? (
              <path d={STAR} fill="var(--c-accent)" />
            ) : (
              <>
                <path d={STAR} fill="none" stroke="var(--c-star-empty)" strokeWidth="1.4" />
                {fill === 'half' && <path d={STAR} fill="var(--c-accent)" clipPath={`url(#${clipId}-${idx})`} />}
              </>
            )}
          </svg>
        </button>
      ))}
    </fieldset>
  )
}

import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { Icon } from '../components/Icon'
import { Stars } from '../components/film'
import { Empty, ErrorPlate, Loading, ScreenHeader } from '../components/ui'
import * as api from '../lib/api'
import { num, runtime } from '../lib/format'
import { haptic } from '../lib/tg'
import { useLoad } from '../lib/useLoad'
import type { FeedItem } from '../lib/types'

const THRESHOLD = 100 // px до срабатывания свайпа
const TAP = 6 // px: меньше — это нажатие, а не свайп

/**
 * Лента — быстрая разметка свайпами: вправо — в «Желаемое», влево — «Не моё».
 * Подсказкой служат штампы, проступающие на карточке при наклоне.
 * Нажатие на карточку открывает фильм.
 */
export function Feed({ onOpenFilm }: { onOpenFilm: (id: number) => void }) {
  const { data, error, loading, reload, setData } = useLoad(() => api.getFeed(), [])
  const [dx, setDx] = useState(0)
  const [leaving, setLeaving] = useState<'left' | 'right'>()
  const [rating, setRating] = useState<number>()
  const [askedToRate, setAskedToRate] = useState(false)
  const start = useRef<number | null>(null)
  const [dragging, setDragging] = useState(false)

  const item = data?.[0]
  const next = data?.[1]

  // Постеры следующих карточек грузим заранее: под наклонённой карточкой
  // должна быть видна уже готовая следующая, а не пустой прямоугольник.
  useEffect(() => {
    data?.slice(1, 4).forEach((f) => {
      if (f.posterUrl) new Image().src = f.posterUrl
    })
  }, [data])

  const advance = () => {
    setData((d) => d?.slice(1))
    setDx(0)
    setLeaving(undefined)
    setRating(undefined)
    setAskedToRate(false)
  }

  const finish = (dir: 'left' | 'right') => {
    if (!item) return
    haptic.impact('medium')
    setLeaving(dir)
    api.swipeFeed(item.id, dir).catch(reload)
    setTimeout(advance, 220)
  }

  const onDown = (e: PointerEvent<HTMLElement>) => {
    if ((e.target as HTMLElement).closest('button, a')) return
    start.current = e.clientX
    setDragging(true)
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onMove = (e: PointerEvent<HTMLElement>) => {
    if (start.current == null) return
    setDx(e.clientX - start.current)
  }
  const onUp = () => {
    if (start.current == null) return
    start.current = null
    setDragging(false)
    if (dx > THRESHOLD) finish('right')
    else if (dx < -THRESHOLD) finish('left')
    else {
      if (Math.abs(dx) < TAP && item) onOpenFilm(item.id)
      setDx(0)
    }
  }

  const markSeen = () => {
    if (!item) return
    if (rating == null && !askedToRate) {
      setAskedToRate(true)
      return
    }
    if (rating != null) api.rateFilm(item.id, rating).catch(reload)
    api.setSeen(item.id, true).catch(reload)
    haptic.notify('success')
    advance()
  }

  const offset = leaving ? (leaving === 'right' ? 480 : -480) : dx
  const hot = dx > 40 ? 'right' : dx < -40 ? 'left' : undefined
  // Следующая карточка «поднимается» по мере наклона текущей
  const lift = Math.min(Math.abs(offset) / THRESHOLD, 1)

  return (
    <div className="screen" style={{ gap: 12 }}>
      <ScreenHeader title="Лента" />

      {error && <ErrorPlate message={error} onRetry={reload} />}
      {!data && loading && <Loading text="Собираем ленту…" />}
      {data && !item && <Empty>Лента кончилась — вы разметили весь каталог. Загляните позже.</Empty>}

      {item && (
        <>
          <div className="feed-stack">
            {next && (
              <div
                className="feed-card feed-card--next"
                aria-hidden="true"
                style={{ transform: `scale(${0.94 + 0.06 * lift})`, opacity: 0.5 + 0.5 * lift }}
              >
                <CardBody item={next} />
              </div>
            )}
            <article
              key={item.id}
              className="feed-card"
              onPointerDown={onDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onUp}
              style={{
                transform: `translateX(${offset}px) rotate(${offset / 20}deg)`,
                transition: dragging ? 'none' : 'transform 0.22s ease-out',
              }}
            >
              {hot === 'right' && <span className="feed-stamp feed-stamp--yes">Хочу посмотреть</span>}
              {hot === 'left' && <span className="feed-stamp feed-stamp--no">Не моё</span>}
              <CardBody item={item} />
            </article>
          </div>

          {/* Для экранных читалок: свайп недоступен — дублируем действие кнопками */}
          <div className="sr-only">
            <button type="button" onClick={() => finish('left')}>Не моё</button>
            <button type="button" onClick={() => finish('right')}>Хочу посмотреть</button>
            <button type="button" onClick={() => onOpenFilm(item.id)}>Открыть карточку фильма</button>
          </div>

          <div className="stack" style={{ gap: 6 }}>
            <div className="row row--between xsmall muted">
              <span>
                {askedToRate && rating == null
                  ? 'Поставьте оценку или нажмите «Смотрел» ещё раз'
                  : 'Уже смотрели? Оцените и отметьте'}
              </span>
              <span style={{ flex: 'none' }}>
                осталось <span className="num" style={{ fontWeight: 800, color: 'var(--c-accent)' }}>{data.length}</span>
              </span>
            </div>
            <div className="row">
              <Stars size="sm" label="Оценка фильма" value={rating} onChange={setRating} />
              <button type="button" className="btn" style={{ flex: 1, minHeight: 48 }} onClick={markSeen}>
                <Icon name="eye" size={18} />
                Смотрел
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function CardBody({ item }: { item: FeedItem }) {
  return (
    <>
      <div className="feed-card__poster">
        {item.posterUrl && <img src={item.posterUrl} alt="" draggable={false} />}
        {item.reason && (
          <span className="chip chip--solid" style={{ alignSelf: 'flex-start', position: 'relative' }}>
            <Icon name="user" size={14} strokeWidth={2} />
            {item.reason}
          </span>
        )}
        {!item.posterUrl && (
          <span className="num" style={{ fontSize: 34, lineHeight: 0.95, color: 'var(--c-line)', textTransform: 'uppercase' }}>
            {item.originalTitle ?? item.title}
          </span>
        )}
      </div>
      <div className="feed-card__body">
        <div className="stack" style={{ gap: 4 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, lineHeight: 1.2 }}>{item.title}</h2>
          <span className="small muted">
            {[item.year, item.runtimeMin && runtime(item.runtimeMin), item.genres.slice(0, 2).join(', ')].filter(Boolean).join(' · ')}
          </span>
        </div>
        <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
          {item.ratings.club != null && (
            <span className="chip chip--accent">клуб {num(item.ratings.club)} ★ · {item.ratings.clubCount}</span>
          )}
          {item.ratings.kp != null && <span className="chip">КП {num(item.ratings.kp)}</span>}
          {item.ratings.tmdb != null && <span className="chip">TMDB {num(item.ratings.tmdb)}</span>}
        </div>
        {item.overview && <p className="feed-card__overview">{item.overview}</p>}
      </div>
    </>
  )
}

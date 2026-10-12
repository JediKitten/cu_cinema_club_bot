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
const REFILL_AT = 8 // карточек в очереди, при которых подгружаем следующую порцию

/**
 * Лента — быстрая разметка свайпами: вправо — в «Желаемое», влево — «Не моё».
 * Подсказкой служат штампы, проступающие на карточке при наклоне.
 * Нажатие на карточку открывает фильм.
 */
export function Feed({ onOpenFilm }: { onOpenFilm: (id: number) => void }) {
  const { data: feed, error, loading, reload, setData: setFeed } = useLoad(() => api.getFeed(), [])
  const data = feed?.items
  const [refilling, setRefilling] = useState(false)
  // Длина очереди, на которой дозагрузка упала: не долбим сервер повторами,
  // следующая попытка — после очередного свайпа.
  const failedAt = useRef<number | null>(null)
  const [dx, setDx] = useState(0)
  const [leaving, setLeaving] = useState<'left' | 'right'>()
  const [rating, setRating] = useState<number>()
  const [askedToRate, setAskedToRate] = useState(false)
  const start = useRef<{ x: number; y: number } | null>(null)
  // Палец сдвинулся заметно — это уже не нажатие, даже если вернулся назад
  const moved = useRef(false)
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

  // Сервер отдаёт ленту порциями: когда очередь подходит к концу, а
  // неразмеченное ещё есть, подгружаем следующую, не повторяя лежащие карточки.
  useEffect(() => {
    if (!feed || refilling || feed.items.length > REFILL_AT || feed.left <= feed.items.length) return
    if (failedAt.current === feed.items.length) return
    setRefilling(true)
    api
      .getFeed(feed.items.map((f) => f.id))
      .then((next) =>
        setFeed((cur) => {
          if (!cur) return cur
          const have = new Set(cur.items.map((f) => f.id))
          const items = [...cur.items, ...next.items.filter((f) => !have.has(f.id))]
          // Свайпы, ещё летящие на сервер, он пока не учёл — берём меньшее
          return { items, left: Math.max(items.length, Math.min(cur.left, next.left)) }
        }),
      )
      .catch(() => {
        failedAt.current = feed.items.length
      })
      .finally(() => setRefilling(false))
  }, [feed, refilling, setFeed])

  const advance = () => {
    setFeed((f) => f && { items: f.items.slice(1), left: Math.max(f.left - 1, 0) })
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
    start.current = { x: e.clientX, y: e.clientY }
    moved.current = false
    setDragging(true)
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onMove = (e: PointerEvent<HTMLElement>) => {
    if (start.current == null) return
    const x = e.clientX - start.current.x
    const y = e.clientY - start.current.y
    if (Math.abs(x) > TAP || Math.abs(y) > TAP) moved.current = true
    // Ведут вертикально — листают описание, а не смахивают карточку
    if (Math.abs(y) > Math.abs(x) && Math.abs(y) > TAP && Math.abs(dx) < TAP) {
      start.current = null
      setDragging(false)
      setDx(0)
      return
    }
    setDx(x)
  }
  const onUp = () => {
    if (start.current == null) return
    start.current = null
    setDragging(false)
    if (dx > THRESHOLD) finish('right')
    else if (dx < -THRESHOLD) finish('left')
    else {
      if (!moved.current && item) onOpenFilm(item.id)
      setDx(0)
    }
  }
  // Прокрутку описания браузер забирает себе и присылает cancel — это не нажатие
  const onCancel = () => {
    start.current = null
    setDragging(false)
    setDx(0)
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
      {feed && !item && (feed.left > 0 ? <Loading text="Подгружаем ещё…" /> : <Empty>Лента кончилась — вы разметили весь каталог. Загляните позже.</Empty>)}

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
              onPointerCancel={onCancel}
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
                осталось <span className="num" style={{ fontWeight: 800, color: 'var(--c-accent)' }}>{feed!.left}</span>
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

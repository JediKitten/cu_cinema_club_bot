import { useEffect, useState, type ReactNode } from 'react'
import { Icon } from '../components/Icon'
import { Logo } from '../components/Logo'
import { FilmRow, MarkLegend, Poster } from '../components/film'
import { Empty, ErrorPlate, Loading, ScreenHeader } from '../components/ui'
import * as api from '../lib/api'
import { weekRange } from '../lib/format'
import { useLoad } from '../lib/useLoad'
import type { Film, Mark, SortKey } from '../lib/types'

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'kp', label: 'Топ Кинопоиска' },
  { key: 'tmdb', label: 'По оценкам TMDB' },
  { key: 'club', label: 'По оценкам клуба' },
  { key: 'want', label: 'Хотят в клубе' },
  { key: 'year', label: 'По году' },
]

const VIEW_KEY = 'kinoclub.catalogView'

function readView(): 'list' | 'grid' {
  try {
    return localStorage.getItem(VIEW_KEY) === 'grid' ? 'grid' : 'list'
  } catch {
    return 'list'
  }
}

export function Catalog({
  onOpenFilm,
  votingWeekStart,
  onOpenVote,
  refreshKey,
  banner,
}: {
  onOpenFilm: (id: number) => void
  /** Если идёт голосование — неделя, на которую голосуем */
  votingWeekStart?: string
  onOpenVote: () => void
  /** Меняется, когда карточка фильма поверх что-то поменяла */
  refreshKey: number
  /** Плашка идущего турнира — над поиском */
  banner?: ReactNode
}) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('kp')
  const [view, setView] = useState(readView)
  const [limit, setLimit] = useState(api.PAGE_SIZE)

  // Поиск от 2 символов с задержкой 0,35 с
  useEffect(() => {
    const t = setTimeout(() => setQuery(input.trim().length >= 2 ? input.trim() : ''), 350)
    return () => clearTimeout(t)
  }, [input])

  const { data, error, loading, reload, setData } = useLoad(
    () => api.getCatalog({ query, sort, limit }),
    [query, sort, limit, refreshKey],
  )

  const changeView = (v: 'list' | 'grid') => {
    setView(v)
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      /* приватный режим — не запоминаем */
    }
  }

  const patch = (id: number, p: Partial<Film>) =>
    setData((d) => d && { ...d, items: d.items.map((f) => (f.id === id ? { ...f, ...p } : f)) })

  const onMark = (id: number, mark: Mark) => {
    patch(id, { mark })
    api.setMark(id, mark).catch(reload)
  }
  const onSeen = (id: number, seen: boolean) => {
    patch(id, { seen })
    api.setSeen(id, seen).catch(reload)
  }

  const searching = query.length > 0

  return (
    <div className="screen">
      <ScreenHeader title="Каталог">
        <Logo />
      </ScreenHeader>

      {!searching && banner}

      {votingWeekStart && !searching && (
        <button type="button" className="banner" onClick={onOpenVote}>
          <span className="stack" style={{ flex: 1, gap: 4 }}>
            <span className="banner__kicker">Идёт голосование</span>
            <span className="banner__title">Выберите фильмы и вечера на {weekRange(votingWeekStart)}</span>
          </span>
          <span className="circle-badge" style={{ width: 44, height: 44, background: 'var(--c-black)', color: 'var(--c-white)' }}>
            <Icon name="arrowRight" size={22} strokeWidth={1.6} />
          </span>
        </button>
      )}

      <label className="search">
        <Icon name="search" size={18} />
        <span className="sr-only">Поиск по каталогу</span>
        <input
          type="search"
          placeholder="Фильм или режиссёр"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          enterKeyHint="search"
        />
        {input && (
          <button type="button" className="btn--text muted" aria-label="Очистить поиск" onClick={() => setInput('')} style={{ height: 44 }}>
            <Icon name="close" size={18} />
          </button>
        )}
      </label>

      {!searching && (
        <div className="row row--between">
          <label className="row" style={{ position: 'relative', minHeight: 44, fontSize: 14, fontWeight: 500 }}>
            <span className="sr-only">Сортировка</span>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              style={{ position: 'absolute', inset: 0, opacity: 0 }}
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
            {SORTS.find((s) => s.key === sort)?.label}
            <span className="muted"><Icon name="chevronDown" size={16} strokeWidth={2} /></span>
          </label>
          <div className="segmented">
            <button type="button" aria-label="Списком" aria-pressed={view === 'list'} onClick={() => changeView('list')}>
              <Icon name="list" size={18} />
            </button>
            <button type="button" aria-label="Плиткой" aria-pressed={view === 'grid'} onClick={() => changeView('grid')}>
              <Icon name="tiles" size={18} />
            </button>
          </div>
        </div>
      )}

      {view === 'list' && <MarkLegend />}

      {error && <ErrorPlate message={error} onRetry={reload} />}
      {!data && loading && <Loading />}

      {data && data.items.length === 0 && (
        <Empty>
          {searching
            ? 'Ничего не нашлось. Если фильма нет и в TMDB — оставьте заявку в профиле: «Не нашёл фильм».'
            : 'Каталог пока пуст. Найдите первый фильм через поиск.'}
        </Empty>
      )}

      {data && view === 'list' && (
        <div>
          {data.items.map((f) => (
            <FilmRow
              key={f.id}
              film={f}
              onOpen={() => onOpenFilm(f.id)}
              onMark={(m) => onMark(f.id, m)}
              onSeen={(v) => onSeen(f.id, v)}
            />
          ))}
        </div>
      )}

      {data && view === 'grid' && (
        <div className="poster-grid">
          {data.items.map((f) => (
            <Poster key={f.id} film={f} width="100%" onClick={() => onOpenFilm(f.id)} />
          ))}
        </div>
      )}

      {data?.hasMore && (
        <button type="button" className="btn btn--block" onClick={() => setLimit((l) => l + api.PAGE_SIZE)}>
          Показать ещё
        </button>
      )}
    </div>
  )
}

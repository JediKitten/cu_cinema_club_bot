import { useState } from 'react'
import { Icon } from '../components/Icon'
import { Poster } from '../components/film'
import { ErrorPlate, ScreenHeader } from '../components/ui'
import * as server from '../legacy/api'
import type { FilmBrief } from '../legacy/types'
import { useSearch } from '../legacy/useLoad'
import { haptic } from '../lib/tg'

const MAX = 4

/** «Любимое» — четыре фильма, которые видят все, кто открывает профиль. */
export function Favorites({ initial, onSaved }: { initial: FilmBrief[]; onSaved: () => void }) {
  const [films, setFilms] = useState(initial)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const { found } = useSearch(query, async (text) => (await server.searchFilms(text)).slice(0, 6), { delay: 350 })

  const save = async (next: FilmBrief[]) => {
    setBusy(true)
    setError(undefined)
    try {
      setFilms(await server.setFavourites(next))
      haptic.select()
      setQuery('')
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen">
      <ScreenHeader title="Любимое" />
      <p className="small muted">До {MAX} фильмов — их увидят все, кто откроет ваш профиль, и по ним вас найдут те, с кем совпадает вкус.</p>

      <div className="grid-4">
        {films.map((f) => (
          <button
            key={f.id ?? `tmdb-${f.tmdb_id}`}
            type="button"
            className="stack"
            style={{ gap: 6, background: 'transparent', border: 0, padding: 0 }}
            disabled={busy}
            aria-label={`Убрать «${f.title_ru}» из любимого`}
            onClick={() => save(films.filter((x) => x !== f))}
          >
            <Poster film={{ title: f.title_ru, posterUrl: f.poster_url ?? undefined }} width="100%" />
            <span className="xsmall muted row" style={{ gap: 4, justifyContent: 'center' }}>
              <Icon name="close" size={12} /> убрать
            </span>
          </button>
        ))}
        {Array.from({ length: Math.max(0, MAX - films.length) }, (_, i) => (
          <span
            key={`slot-${i}`}
            style={{ aspectRatio: '2 / 3', borderRadius: 'var(--r-s)', border: '1.5px dashed var(--c-line-strong)' }}
          />
        ))}
      </div>

      {error && <ErrorPlate message={error} />}

      {films.length >= MAX ? (
        <p className="small muted">Больше {MAX} не помещается — уберите один, чтобы добавить другой.</p>
      ) : (
        <>
          <label className="search">
            <Icon name="search" size={18} />
            <span className="sr-only">Найти фильм</span>
            <input type="search" placeholder="Найти фильм" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          {found.map((f) => (
            <button
              key={f.id ?? `tmdb-${f.tmdb_id}`}
              type="button"
              className="menu__item"
              disabled={busy}
              onClick={() => save([...films, f])}
            >
              <span className="menu__label">
                {f.title_ru}
                <span className="small muted">{f.year ? ` · ${f.year}` : ''}{f.id === null ? ' · найдено в TMDB' : ''}</span>
              </span>
              <Icon name="plus" size={18} />
            </button>
          ))}
        </>
      )}
    </div>
  )
}

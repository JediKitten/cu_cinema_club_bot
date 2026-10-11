import { lazy, Suspense, useState } from 'react'
import { Icon } from '../components/Icon'
import { MarkButtons, SeenToggle, Stars } from '../components/film'
import { ErrorPlate, Loading } from '../components/ui'
import * as api from '../lib/api'
import { num, plural, runtime } from '../lib/format'
import { haptic, openLink } from '../lib/tg'
import * as server from '../legacy/api'
import { shareLink } from '../legacy/telegram'

// Статистика клуба по фильму — только админам, и тянуть её код остальным незачем.
const FilmStatsPanel = lazy(() =>
  import('../legacy/components/FilmStatsPanel').then((m) => ({ default: m.FilmStatsPanel })),
)
import { useLoad } from '../lib/useLoad'
import type { Film } from '../lib/types'

/** Карточка фильма — оверлей поверх любой вкладки. Назад — системная кнопка Telegram. */
export function FilmCard({ filmId, onChanged, withStats = false }: { filmId: number; onChanged: () => void; withStats?: boolean }) {
  const { data: film, error, reload, setData } = useLoad(() => api.getFilm(filmId), [filmId])
  const [inviteOpen, setInviteOpen] = useState(false)

  if (error && !film) return <div className="screen"><ErrorPlate message={error} onRetry={reload} /></div>
  if (!film) return <Loading />

  const patch = (p: Partial<Film>, call: Promise<void>) => {
    setData((f) => f && { ...f, ...p })
    call.then(onChanged).catch(reload)
  }

  const meta = [film.originalTitle, film.year, film.runtimeMin && runtime(film.runtimeMin)].filter(Boolean).join(' · ')

  return (
    <div className="screen screen--overlay">
      <div
        className="poster"
        style={{ width: '100%', height: 420, borderRadius: 20, padding: 16, position: 'relative', alignItems: 'stretch', flexDirection: 'column', justifyContent: 'space-between' }}
      >
        {film.posterUrl && <img src={film.posterUrl} alt="" style={{ position: 'absolute', inset: 0, margin: 0, width: '100%', height: '100%' }} />}
        {film.seen && (
          <span className="chip chip--solid" style={{ alignSelf: 'flex-end', position: 'relative', background: 'var(--c-black)', color: 'var(--c-accent)', fontFamily: 'var(--f-body)', fontSize: 12, textTransform: 'none' }}>
            <Icon name="check" size={14} strokeWidth={2.4} />
            Просмотрено
          </span>
        )}
      </div>

      {film.invitedBy && (
        <div className="card card--pad small">
          {film.invitedBy} зовёт вас на этот фильм. Решать вам — отметьте, если пойдёте.
        </div>
      )}

      <div className="stack">
        <div className="row row--between" style={{ alignItems: 'flex-start' }}>
          <h1 className="h-film">{film.title}</h1>
          <SeenToggle seen={film.seen} onChange={(seen) => patch({ seen }, api.setSeen(film.id, seen))} />
        </div>
        <p className="small muted" style={{ fontSize: 14 }}>
          {meta}
          {film.genres.length > 0 && <><br />{film.genres.join(', ')}</>}
          {film.directors.length > 0 && <><br />Режиссёр: {film.directors.join(', ')}</>}
        </p>
      </div>

      <div className="stack" style={{ gap: 10 }}>
        <MarkButtons mark={film.mark} size="card" onChange={(mark) => patch({ mark }, api.setMark(film.id, mark))} />
        <p className="small muted">
          «Ближайшее» весит втрое больше при сборе шорт-листа и через 2 недели само станет «Желаемым».
        </p>
      </div>

      <button type="button" className="btn btn--lg" style={{ minHeight: 48 }} aria-expanded={inviteOpen} onClick={() => setInviteOpen((v) => !v)}>
        <Icon name="share" size={18} />
        Позвать друзей
      </button>
      {inviteOpen && <InviteBlock filmId={film.id} />}

      <section aria-label="Рейтинги" className="grid-2">
        <RatingTile accent label="Клуб" value={film.ratings.club != null ? `${num(film.ratings.club)} ★` : '—'} sub={`${film.ratings.clubCount} ${plural(film.ratings.clubCount, ['оценка', 'оценки', 'оценок'])}`} />
        <RatingTile label="Хотят посмотреть" value={String(film.ratings.wantCount)} sub={plural(film.ratings.wantCount, ['участник', 'участника', 'участников'])} />
        <RatingTile label="Кинопоиск" value={film.ratings.kp != null ? num(film.ratings.kp) : '—'} sub="из 10" />
        <RatingTile label="TMDB" value={film.ratings.tmdb != null ? num(film.ratings.tmdb) : '—'} sub="из 10" />
      </section>

      {!film.fromTmdb && (
        <section className="stack">
          <h2 className="h-section">{film.myRating != null ? `Ваша оценка · ${num(film.myRating)}` : 'Оцените фильм'}</h2>
          <Stars
            label="Ваша оценка"
            value={film.myRating}
            onChange={(myRating) => patch({ myRating }, api.rateFilm(film.id, myRating))}
          />
        </section>
      )}

      {film.trailerUrl && (
        <button type="button" className="btn--link row" style={{ fontSize: 15, gap: 10 }} onClick={() => openLink(film.trailerUrl!)}>
          <span className="circle-badge circle-badge--lilac" style={{ width: 36, height: 36 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill="currentColor" /></svg>
          </span>
          Смотреть трейлер
        </button>
      )}

      {film.overview && <p style={{ color: 'var(--c-text-body)', lineHeight: 1.55 }}>{film.overview}</p>}

      {film.reviews.length > 0 && (
        <section className="stack" style={{ gap: 12 }}>
          <h2 className="h-section">Отзывы клуба</h2>
          {film.reviews.map((r) => (
            <article key={r.id} className="card card--pad stack">
              <div className="row" style={{ gap: 10 }}>
                <span className="avatar" style={{ width: 32, height: 32, fontSize: 13, background: 'var(--c-line)', color: 'var(--c-accent)', fontFamily: 'var(--f-body)', fontWeight: 600 }}>
                  {r.author[0]}
                </span>
                <span style={{ flex: 1, fontSize: 14, fontWeight: 600 }}>{r.author}</span>
                {r.rating != null && <span className="small" style={{ color: 'var(--c-accent)' }}>{num(r.rating, r.rating % 1 ? 1 : 0)} ★</span>}
              </div>
              <p style={{ fontSize: 14, color: 'var(--c-text-body)' }}>{r.text}</p>
            </article>
          ))}
        </section>
      )}

      {withStats && film.id > 0 && (
        <details className="card card--pad">
          <summary className="h-section" style={{ cursor: 'pointer' }}>Статистика клуба</summary>
          <div className="legacy" style={{ marginTop: 12 }}>
            <Suspense fallback={<Loading />}>
              <FilmStatsPanel filmId={film.id} />
            </Suspense>
          </div>
        </details>
      )}

      <p className="xsmall" style={{ color: 'var(--c-text-3)' }}>
        Данные о фильме — TMDB. Этот продукт использует API TMDB, но не одобрен и не сертифицирован TMDB.
      </p>
    </div>
  )
}

function RatingTile({ label, value, sub, accent }: { label: string; value: string; sub: string; accent?: boolean }) {
  return (
    <div className={`card card--pad stack${accent ? ' card--accent' : ''}`} style={{ gap: 4 }}>
      <span className={`xsmall${accent ? '' : ' muted'}`} style={{ fontWeight: 600 }}>{label}</span>
      <span className="num" style={{ fontSize: 26 }}>{value}</span>
      <span className={`xsmall${accent ? '' : ' muted'}`}>{sub}</span>
    </div>
  )
}

/** Приглашение на фильм: ссылка ведёт друга прямо в карточку. Голос за него
 *  она не ставит — решает он сам. */
function InviteBlock({ filmId }: { filmId: number }) {
  const { data: invite, error } = useLoad(
    () => (filmId > 0 ? server.getInvite(filmId) : Promise.resolve(undefined)),
    [filmId],
  )
  const [copied, setCopied] = useState(false)

  if (filmId < 0) {
    return <div className="card card--pad small muted">Отметьте фильм — тогда по нему можно будет позвать друзей.</div>
  }
  if (error) return <ErrorPlate message={error} />
  if (!invite) return <Loading />

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(invite.link)
      setCopied(true)
      haptic.notify('success')
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="card card--pad stack" style={{ gap: 10 }}>
      <p className="small muted">Ссылка зовёт именно на этот фильм. Голос за друга она не ставит — он решит сам.</p>
      <input className="field" readOnly value={invite.link} onFocus={(e) => e.target.select()} />
      <div className="grid-2">
        <button type="button" className={copied ? 'btn btn--white' : 'btn'} onClick={copy}>
          <Icon name={copied ? 'check' : 'copy'} size={16} />
          {copied ? 'Скопировано' : 'Скопировать'}
        </button>
        <button type="button" className="btn btn--primary" onClick={() => shareLink(invite.link)}>
          <Icon name="share" size={16} />
          Переслать
        </button>
      </div>
      {invite.invited > 0 && (
        <p className="xsmall muted">По вашим ссылкам пришли {invite.invited}, отметили фильм {invite.accepted}.</p>
      )}
    </div>
  )
}

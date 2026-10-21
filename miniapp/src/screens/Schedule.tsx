import { useState } from 'react'
import { Icon } from '../components/Icon'
import { Poster } from '../components/film'
import { CheckIcon } from '../components/film'
import { CheckMark, Empty, ErrorPlate, Loading, ScreenHeader, Ticket } from '../components/ui'
import * as api from '../lib/api'
import { eveningDate, showDate, weekRange } from '../lib/format'
import { haptic, openLink, tgConfirm } from '../lib/tg'
import { useLoad } from '../lib/useLoad'
import type { Ballot, Show, Week, WeekStage } from '../lib/types'

/** Неотправленный выбор переживает уход с вкладки. */
const drafts = new Map<string, { films: number[]; evenings: number[] }>()

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

export function Schedule({
  weekStart,
  onWeekChange,
  onOpenFilm,
  onCheckIn,
}: {
  weekStart?: string
  onWeekChange: (week: string) => void
  onOpenFilm: (id: number) => void
  onCheckIn: (show: Show) => void
}) {
  const { data, error, loading, reload, setData } = useLoad(() => api.getSchedule(weekStart), [weekStart])

  return (
    <div className="screen">
      <ScreenHeader title="Расписание" />
      {error && <ErrorPlate message={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && (
        <>
          <WeekNav week={data.week} onChange={onWeekChange} />
          <Stages stage={data.week.stage} />
          {data.week.votingWeekStart && data.week.votingWeekStart !== data.week.start && (
            <button type="button" className="banner banner--outline" onClick={() => onWeekChange(data.week.votingWeekStart!)}>
              Идёт выбор фильмов на {weekRange(data.week.votingWeekStart)}
              <Icon name="arrowRight" size={18} />
            </button>
          )}
          {data.ballot ? (
            <BallotView
              key={data.ballot.weekStart}
              ballot={data.ballot}
              onOpenFilm={onOpenFilm}
              onSaved={(b) => setData((d) => d && { ...d, ballot: b })}
            />
          ) : (
            <ShowsList
              shows={data.shows}
              onOpenFilm={onOpenFilm}
              onCheckIn={onCheckIn}
              onStatus={(id, myStatus) =>
                setData((d) => d && { ...d, shows: d.shows.map((s) => (s.id === id ? { ...s, myStatus } : s)) })
              }
              onError={reload}
            />
          )}
        </>
      )}
    </div>
  )
}

/* ---------- Навигация по неделям ---------- */

function WeekNav({ week, onChange }: { week: Week; onChange: (w: string) => void }) {
  return (
    <div className="week-nav">
      <button type="button" className="circle-btn" aria-label="Прошлая неделя" disabled={!week.hasPrev} onClick={() => onChange(addDays(week.start, -7))}>
        <Icon name="arrowLeft" size={20} strokeWidth={1.6} />
      </button>
      <span className="week-nav__label">{weekRange(week.start)}</span>
      <button type="button" className="circle-btn" aria-label="Следующая неделя" disabled={!week.hasNext} onClick={() => onChange(addDays(week.start, 7))}>
        <Icon name="arrowRight" size={20} strokeWidth={1.6} />
      </button>
    </div>
  )
}

/* ---------- Этап недели: сбор → голосование → расписание ---------- */

const STEPS: { label: string; hint: string }[] = [
  { label: 'Сбор интереса', hint: 'до ср 20:00' },
  { label: 'Голосование', hint: 'чт–сб' },
  { label: 'Расписание', hint: 'вс' },
]
const STAGE_INDEX: Record<WeekStage, number> = { collect: 0, vote: 1, schedule: 2, shows: 3 }

function Stages({ stage }: { stage: WeekStage }) {
  const current = STAGE_INDEX[stage]
  return (
    <ol className="stages card" aria-label="Этап недели">
      {STEPS.map((s, i) => {
        const state = i < current ? 'done' : i === current ? 'current' : 'next'
        return (
          <li key={s.label} data-state={state} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="stages__bar" />
            <span>
              {s.label}
              <br />
              {state === 'done' ? <CheckIcon size={12} /> : s.hint}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

/* ---------- Режим 1: бюллетень ---------- */

function BallotView({ ballot, onOpenFilm, onSaved }: { ballot: Ballot; onOpenFilm: (id: number) => void; onSaved: (b: Ballot) => void }) {
  const saved = { films: ballot.selectedFilmIds, evenings: ballot.selectedEveningIds }
  const [sel, setSel] = useState(() => drafts.get(ballot.weekStart) ?? saved)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const same = (a: number[], b: number[]) => a.length === b.length && a.every((x) => b.includes(x))
  const dirty = !same(sel.films, saved.films) || !same(sel.evenings, saved.evenings)

  const toggle = (key: 'films' | 'evenings', id: number) => {
    haptic.select()
    setSel((s) => {
      const list = s[key].includes(id) ? s[key].filter((x) => x !== id) : [...s[key], id]
      const next = { ...s, [key]: list }
      drafts.set(ballot.weekStart, next)
      return next
    })
  }

  const save = async () => {
    setBusy(true)
    setError(undefined)
    try {
      const b = await api.saveBallot(ballot.weekStart, sel.films, sel.evenings, ballot.fixedSlot)
      drafts.delete(ballot.weekStart)
      haptic.notify('success')
      onSaved(b)
    } catch (e) {
      haptic.notify('error')
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const needEvening = !ballot.fixedSlot && sel.films.length > 0 && sel.evenings.length === 0
  const fixedAt = ballot.fixedSlot && ballot.evenings[0] ? eveningDate(ballot.evenings[0].startsAt) : undefined

  return (
    <>
      {ballot.preview && (
        <p className="warn">Предпросмотр — голосование видите только вы. Остальные увидят его после публикации шорт-листа.</p>
      )}
      {(ballot.theme || fixedAt) && (
        <div className="banner" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
          {ballot.theme && <span className="banner__title" style={{ fontWeight: 700 }}>{ballot.theme}</span>}
          {fixedAt && (
            <span style={{ fontSize: 14, lineHeight: 1.35 }}>
              Время уже назначено: <b>{fixedAt.weekday} {fixedAt.text}</b>
. Выбирать вечер не нужно — голосуем только за фильм.
            </span>
          )}
        </div>
      )}
      <p className="small muted">
        {ballot.fixedSlot ? 'Отметьте фильмы, на которые пошли бы, — покажем тот, что наберёт больше голосов.' : 'Выберите фильмы и вечера — расписание соберём из ответов.'}
      </p>
      {ballot.english && <div className="lang-tag">EN · показ этой недели на английском</div>}

      <section>
        <div className="section-head" style={{ marginBottom: 4 }}>
          <h2 className="h-section" style={{ fontSize: 14 }}>На что пошли бы</h2>
          <span className="small muted">выбрано {sel.films.length}</span>
        </div>
        <p className="small muted" style={{ marginBottom: 6 }}>Отмечайте сколько угодно — это не рейтинг.</p>
        {ballot.films.map((f) => {
          const on = sel.films.includes(f.id)
          return (
            <div key={f.id} className="row" style={{ gap: 12, borderTop: '1px solid var(--c-line-soft)' }}>
              <Poster film={f} width={44} height={64} onClick={() => onOpenFilm(f.id)} />
              <button type="button" className="check-row" style={{ borderTop: 0 }} aria-pressed={on} onClick={() => toggle('films', f.id)}>
                <span className="stack" style={{ flex: 1, gap: 3 }}>
                  <span style={{ fontWeight: 600 }}>{f.title}</span>
                  <span className="small muted">{[f.year, f.directors[0]].filter(Boolean).join(' · ')}</span>
                </span>
                <CheckMark on={on} />
              </button>
            </div>
          )
        })}
      </section>

      {!ballot.fixedSlot && <section>
        <h2 className="h-section" style={{ fontSize: 14, marginBottom: 6 }}>Когда свободны</h2>
        {ballot.evenings.filter((e) => !e.closed).map((e) => {
          const on = sel.evenings.includes(e.id)
          const d = eveningDate(e.startsAt)
          return (
            <button key={e.id} type="button" className="check-row" aria-pressed={on} onClick={() => toggle('evenings', e.id)}>
              <span className="day-label">{d.weekday}</span>
              <span className="stack" style={{ flex: 1, gap: 3 }}>
                <span style={{ fontWeight: 600 }}>{d.text}</span>
                <span className="small muted">{e.place}</span>
              </span>
              <CheckMark on={on} />
            </button>
          )
        })}
        {needEvening && <p className="warn" style={{ marginTop: 6 }}>Отметьте хотя бы один вечер — иначе голос за фильмы не учтётся.</p>}
      </section>}

      {error && <ErrorPlate message={error} />}

      <div className="sticky-bar" style={{ position: 'sticky', bottom: -24, margin: '0 calc(-1 * var(--gutter)) -24px' }}>
        <button type="button" className="btn btn--primary btn--lg btn--block" disabled={!dirty || busy} onClick={save}>
          {dirty ? (busy ? 'Сохраняем…' : 'Сохранить выбор') : <><CheckIcon />Сохранено</>}
        </button>
      </div>
    </>
  )
}

/* ---------- Режим 2: показы недели ---------- */

function ShowsList({
  shows,
  onOpenFilm,
  onCheckIn,
  onStatus,
  onError,
}: {
  shows: Show[]
  onOpenFilm: (id: number) => void
  onCheckIn: (s: Show) => void
  onStatus: (id: number, status: Show['myStatus']) => void
  onError: () => void
}) {
  const active = shows.filter((s) => s.state !== 'cancelled')
  const cancelled = shows.filter((s) => s.state === 'cancelled')

  if (active.length === 0 && cancelled.length === 0) {
    return <Empty>На этой неделе показов нет. Отмечайте фильмы в каталоге — из отметок собирается шорт-лист.</Empty>
  }

  const toggleGoing = async (s: Show) => {
    const isIn = s.myStatus === 'going' || s.myStatus === 'queued'
    if (isIn && !(await tgConfirm('Отменить запись на показ?'))) return
    haptic.select()
    try {
      onStatus(s.id, await api.setAttendance(s.id, !isIn))
    } catch {
      onError()
    }
  }

  return (
    <>
      {active.some((s) => s.state !== 'past') && <p className="small muted">Отметьте, на какие сеансы придёте.</p>}
      {active.map((s) => (
        <ShowTicket key={s.id} show={s} onOpenFilm={onOpenFilm} onToggle={() => toggleGoing(s)} onCheckIn={() => onCheckIn(s)} />
      ))}
      {cancelled.length > 0 && (
        <section className="stack">
          <h2 className="h-section">Отменены</h2>
          {cancelled.map((s) => (
            <div key={s.id} className="card card--pad small" style={{ opacity: 0.6 }}>
              {showDate(s.startsAt).day} · {s.film?.title ?? s.title}
              {s.cancelReason && <span className="muted"> — {s.cancelReason}</span>}
            </div>
          ))}
        </section>
      )}
    </>
  )
}

function ShowTicket({ show: s, onOpenFilm, onToggle, onCheckIn }: { show: Show; onOpenFilm: (id: number) => void; onToggle: () => void; onCheckIn: () => void }) {
  const d = showDate(s.startsAt)
  const title = s.film?.title ?? s.title ?? 'Событие клуба'
  const full = s.going >= s.capacity
  const variant = s.state === 'live' ? 'active' : s.state === 'past' ? 'past' : undefined

  const counter =
    s.state === 'past'
      ? `Пришли ${s.going} из ${s.capacity}`
      : full
        ? `Мест нет · ${s.going} из ${s.capacity}${s.queueLength ? ` · в очереди ${s.queueLength}` : ''}`
        : `Придут ${s.going} из ${s.capacity}`

  return (
    <Ticket
      variant={variant}
      top={
        <div className="ticket__top">
          <div className="stack" style={{ flex: 1, gap: 6 }}>
            {s.state === 'live' && <span className="live-tag">Идёт сейчас</span>}
            <span className="ticket__date">{d.day}<br />{d.time}</span>
            {s.film ? (
              <button type="button" className="btn--text" style={{ padding: 0, textAlign: 'left', fontSize: 16, fontWeight: 600 }} onClick={() => onOpenFilm(s.film!.id)}>
                {title}
              </button>
            ) : (
              <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
            )}
            <span className="small muted">{s.place}</span>
            {s.note && <span className="small muted">{s.note}</span>}
            {s.english && <span className="lang-tag">EN · без дубляжа</span>}
          </div>
          {s.film && <Poster film={s.film} width={64} height={92} onClick={() => onOpenFilm(s.film!.id)} />}
        </div>
      }
      bottom={
        <div className="ticket__bottom">
          <span className="small muted">
            {counter}
            {s.myStatus === 'queued' && s.queuePosition ? ` · вы ${s.queuePosition}-й в очереди` : ''}
          </span>
          {s.state === 'past' ? (
            <span className={s.myStatus === 'attended' ? 'btn btn--white' : 'btn'} style={{ alignSelf: 'flex-end', minHeight: 32, fontSize: 13 }}>
              {s.myStatus === 'attended' ? <><CheckIcon />Вы были</> : 'Вы не были'}
            </span>
          ) : (
            <>
              <div className="grid-2">
                <AttendButton show={s} onClick={onToggle} />
                {s.state === 'live' ? (
                  <button type="button" className="btn btn--primary" style={{ minHeight: 48 }} onClick={onCheckIn}>Я на месте</button>
                ) : (
                  s.calendarUrl && (
                    <button type="button" className="btn" style={{ minHeight: 48 }} onClick={() => openLink(s.calendarUrl!)}>
                      <Icon name="calendarPlus" size={16} />В календарь
                    </button>
                  )
                )}
              </div>
              {(s.myStatus === 'going' || s.myStatus === 'queued') && s.registrationUrl && (
                <button type="button" className="banner banner--outline" onClick={() => openLink(s.registrationUrl!)}>
                  Не забудьте зарегистрироваться в @cu_clubs_bot
                  <Icon name="arrowRight" size={18} />
                </button>
              )}
            </>
          )}
        </div>
      }
    />
  )
}

function AttendButton({ show: s, onClick }: { show: Show; onClick: () => void }) {
  const full = s.going >= s.capacity
  if (s.myStatus === 'going')
    return <button type="button" className="btn btn--white" style={{ minHeight: 48 }} aria-pressed onClick={onClick}><CheckIcon />Приду</button>
  if (s.myStatus === 'queued')
    return <button type="button" className="btn btn--dashed" style={{ minHeight: 48 }} aria-pressed onClick={onClick}>В очереди</button>
  return (
    <button type="button" className={full ? 'btn btn--dashed' : 'btn'} style={{ minHeight: 48 }} aria-pressed={false} onClick={onClick}>
      {full ? 'Встать в очередь' : 'Приду'}
    </button>
  )
}

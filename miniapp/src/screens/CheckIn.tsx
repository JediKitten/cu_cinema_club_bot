import { useEffect, useRef, useState } from 'react'
import { Poster } from '../components/film'
import { ErrorPlate, Ticket } from '../components/ui'
import * as api from '../lib/api'
import { showDate } from '../lib/format'
import { haptic } from '../lib/tg'
import type { Show } from '../lib/types'

const LEN = 6

/** Отметка в зале кодом с экрана. После успеха — опрос на том же месте. */
export function CheckIn({ show, onDone }: { show: Show; onDone: () => void }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const d = showDate(show.startsAt)
  const inputRef = useRef<HTMLInputElement>(null)
  // Клавиатура открывается сразу — человек стоит в зале с кодом перед глазами
  useEffect(() => inputRef.current?.focus(), [])

  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      await api.checkIn(show.id, code)
      haptic.notify('success')
      onDone()
    } catch (e) {
      haptic.notify('error')
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen" style={{ gap: 20 }}>
      <Ticket
        top={
          <div className="ticket__top" style={{ alignItems: 'center' }}>
            {show.film && <Poster film={show.film} width={56} height={80} />}
            <div className="stack" style={{ flex: 1, gap: 4 }}>
              <span style={{ fontSize: 17, fontWeight: 600 }}>{show.film?.title ?? show.title}</span>
              <span className="small muted">{d.day} · {d.time} · {show.place}</span>
            </div>
          </div>
        }
        bottom={
          <form
            className="ticket__bottom"
            style={{ gap: 16, paddingBottom: 20 }}
            onSubmit={(e) => {
              e.preventDefault()
              if (code.length >= 4 && !busy) void submit()
            }}
          >
            <div className="stack" style={{ gap: 6 }}>
              <h1 className="h-screen">Код с экрана</h1>
              <p className="muted" style={{ fontSize: 14 }}>Введите цифры, которые показывают в зале. Код меняется каждую минуту.</p>
            </div>
            <label className="code-cells">
              <span className="sr-only">Код из 6 цифр</span>
              {Array.from({ length: LEN }, (_, i) => (
                <span key={i} className="code-cell" data-active={i === code.length} aria-hidden="true">
                  {code[i] ?? ''}
                </span>
              ))}
              <input
                className="code-input"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={LEN}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, LEN))}
                ref={inputRef}
              />
            </label>
            {error && <ErrorPlate message={error} />}
            <button type="submit" className="btn btn--primary btn--lg" disabled={code.length < 4 || busy}>
              {busy ? 'Проверяем…' : 'Отметиться'}
            </button>
          </form>
        }
      />
      <p className="small muted">
        Код принимают только в первые минуты сеанса и только у записавшихся. Опоздали — подойдите к ведущему, он отметит по списку.
      </p>
    </div>
  )
}

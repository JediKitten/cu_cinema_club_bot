import { useState, type ReactNode } from 'react'
import { CheckIcon, Stars } from '../components/film'
import { ErrorPlate, Loading, Ticket } from '../components/ui'
import * as api from '../lib/api'
import { showDate } from '../lib/format'
import { haptic, tgAlert } from '../lib/tg'
import { useLoad } from '../lib/useLoad'
import type { Survey as SurveyData, SurveyAnswers } from '../lib/types'

/** Опрос после показа (CSAT). Все вопросы необязательны, форма всегда открыта. */
export function Survey({ showId, onDone }: { showId: number; onDone: () => void }) {
  const { data, error, reload } = useLoad(() => api.getSurvey(showId), [showId])
  if (error && !data) return <div className="screen"><ErrorPlate message={error} onRetry={reload} /></div>
  if (!data) return <Loading />
  return <SurveyForm key={showId} survey={data} onDone={onDone} />
}

function SurveyForm({ survey: data, onDone }: { survey: SurveyData; onDone: () => void }) {
  const showId = data.show.id
  // При повторном открытии поля заполнены прежними ответами
  const [answers, setAnswers] = useState<SurveyAnswers>(data.answers)
  const [busy, setBusy] = useState(false)
  const [sendError, setSendError] = useState<string>()

  const set = (p: Partial<SurveyAnswers>) => setAnswers((a) => ({ ...a, ...p }))
  const d = showDate(data.show.startsAt)
  const discussionStars = typeof answers.discussion === 'number' ? answers.discussion : undefined

  const submit = async () => {
    setBusy(true)
    setSendError(undefined)
    try {
      await api.submitSurvey(showId, answers, data.hideFilmQuestion)
      haptic.notify('success')
      await tgAlert('Спасибо! Ответы сохранены')
      onDone()
    } catch (e) {
      setSendError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen" style={{ gap: 20 }}>
      <Ticket
        variant="accent"
        top={
          <div className="stack" style={{ padding: 16, gap: 6 }}>
            <div className="row row--between">
              <span className="banner__kicker row" style={{ fontSize: 11, gap: 4 }}><CheckIcon size={12} />Присутствие отмечено</span>
              <span style={{ fontSize: 11 }}>билет #{data.ticketNo}</span>
            </div>
            <h1 className="h-film" style={{ fontSize: 24 }}>{data.show.film?.title ?? data.show.title}</h1>
            <span className="small">{d.day} · {d.time} · {data.show.place}</span>
          </div>
        }
        bottom={
          <p className="small" style={{ padding: '8px 16px 16px' }}>
            Клуб отчитывается перед университетом, поэтому отвечайте честно. Четыре вопроса, полминуты.
          </p>
        }
      />

      <Question title="Насколько вам понравилось посещение в целом?">
        <Stars label="Посещение в целом" value={answers.overall} onChange={(overall) => set({ overall })} />
      </Question>

      {!data.hideFilmQuestion && (
        <Question title="Как бы вы оценили фильм?" note="Это станет вашей оценкой фильма в клубе.">
          <Stars label="Оценка фильма" value={answers.film} onChange={(film) => set({ film })} />
        </Question>
      )}

      <Question title="Как бы вы оценили обсуждение после фильма?">
        <Stars label="Обсуждение" value={discussionStars} onChange={(v) => set({ discussion: v })} />
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {([['absent', 'Не был на обсуждении'], ['unsure', 'Затрудняюсь ответить']] as const).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className="mark"
              data-variant="wish"
              aria-pressed={answers.discussion === key}
              style={{ height: 40 }}
              onClick={() => {
                haptic.select()
                set({ discussion: answers.discussion === key ? undefined : key })
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </Question>

      <label className="stack" style={{ gap: 10 }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>Любые предложения или критика?</span>
        <textarea
          className="field"
          rows={4}
          placeholder="Что стоит исправить или повторить"
          value={answers.comment}
          onChange={(e) => set({ comment: e.target.value })}
        />
      </label>

      {sendError && <ErrorPlate message={sendError} />}

      <div className="stack">
        <button type="button" className="btn btn--primary btn--lg" disabled={busy} onClick={submit}>
          {busy ? 'Отправляем…' : 'Отправить'}
        </button>
        <p className="small muted" style={{ textAlign: 'center' }}>Ответы можно поправить — форма всегда открыта.</p>
      </div>
    </div>
  )
}

function Question({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="stack" style={{ gap: 6 }}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, lineHeight: 1.35 }}>{title}</h2>
      {note && <p className="small muted">{note}</p>}
      {children}
    </section>
  )
}

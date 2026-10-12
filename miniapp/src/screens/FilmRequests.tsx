import { useState } from 'react'
import { Empty, ErrorPlate, Loading, ScreenHeader } from '../components/ui'
import * as server from '../legacy/api'
import type { FilmRequest } from '../legacy/types'
import { useLoad } from '../lib/useLoad'
import { haptic } from '../lib/tg'

const STATUS: Record<FilmRequest['status'], string> = {
  pending: 'на модерации',
  approved: 'добавлен',
  rejected: 'отклонён',
}

/** «Не нашёл фильм» и «Мои заявки» — одна страница: форма сверху, история ниже. */
export function FilmRequests() {
  const { data, error, loading, setData, reload } = useLoad(() => server.myFilmRequests(), [])
  const [title, setTitle] = useState('')
  const [year, setYear] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [sendError, setSendError] = useState<string>()

  const submit = async () => {
    if (!title.trim() || busy) return
    setBusy(true)
    setSendError(undefined)
    try {
      const created = await server.createFilmRequest({
        raw_title: title.trim(),
        raw_year: year.trim() ? Number(year) : null,
        note: note.trim() || null,
      })
      setData((list) => [created, ...(list ?? [])])
      setTitle('')
      setYear('')
      setNote('')
      haptic.notify('success')
    } catch (e) {
      setSendError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen">
      <ScreenHeader title="Мои заявки" />

      <section className="stack" style={{ gap: 10 }}>
        <p className="small muted">Если фильма нет ни в каталоге, ни в поиске — оставьте заявку, её разберут модераторы. Ответ придёт в бот.</p>
        <input className="field" placeholder="Название" value={title} onChange={(e) => setTitle(e.target.value)} />
        <input className="field" placeholder="Год (необязательно)" inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, '').slice(0, 4))} />
        <input className="field" placeholder="Ссылка или комментарий (необязательно)" value={note} onChange={(e) => setNote(e.target.value)} />
        {sendError && <ErrorPlate message={sendError} />}
        <button type="button" className="btn btn--primary btn--lg" disabled={!title.trim() || busy} onClick={submit}>
          {busy ? 'Отправляем…' : 'Отправить заявку'}
        </button>
      </section>

      <section className="stack" style={{ gap: 10 }}>
        <h2 className="h-section">Мои заявки</h2>
        {error && <ErrorPlate message={error} onRetry={reload} />}
        {!data && loading && <Loading />}
        {data && data.length === 0 && <Empty>Заявок пока нет.</Empty>}
        {data?.map((r) => (
          <article key={r.id} className="card card--pad stack" style={{ gap: 4 }}>
            <div className="row row--between">
              <span style={{ fontWeight: 600 }}>{r.raw_title}{r.raw_year ? ` (${r.raw_year})` : ''}</span>
              <span className={`small${r.status === 'approved' ? '' : ' muted'}`} style={r.status === 'approved' ? { color: 'var(--c-accent)' } : undefined}>
                {STATUS[r.status]}
              </span>
            </div>
            {r.resolution_comment && <p className="small muted">{r.resolution_comment}</p>}
          </article>
        ))}
      </section>
    </div>
  )
}

import { useState } from 'react'
import { Icon, type IconName } from '../components/Icon'
import { AchievementTierList } from '../legacy/components/Achievements'
import { Trophy } from '../legacy/components/Trophy'
import { CheckIcon, Poster } from '../components/film'
import { ErrorPlate, Loading } from '../components/ui'
import * as api from '../lib/api'
import { maxIndex, num, plural } from '../lib/format'
import { haptic } from '../lib/tg'
import { useLoad } from '../lib/useLoad'
import type { Role } from '../lib/types'

export type ProfileSection = 'marked' | 'seen' | 'friends' | 'favorites' | 'club' | 'history' | 'requests'

const ROLE_LABEL: Record<Role, string> = {
  user: 'участник клуба',
  moderator: 'модератор',
  admin: 'админ',
  superadmin: 'главный администратор',
}

const AXIS = ['0,5', '1', '1,5', '2', '2,5', '3', '3,5', '4', '4,5', '5']

/**
 * Свой профиль. Пункты бывшего «Ещё» (☰) вынесены списком внизу —
 * «Управление клубом» больше не спрятано за иконкой.
 */
export function Profile({
  userId,
  onOpenFilm,
  onOpen,
  refreshKey = 0,
}: {
  userId: number
  onOpenFilm: (id: number) => void
  onOpen: (s: ProfileSection) => void
  /** Меняется, когда вложенный экран что-то поменял (любимое, заявки) */
  refreshKey?: number
}) {
  const { data: p, error, reload } = useLoad(() => api.getProfile(userId), [userId, refreshKey])
  const [busy, setBusy] = useState(false)
  // Медали — вкладки: нажатие раскрывает список своей редкости, повторное сворачивает
  const [tier, setTier] = useState<'bronze' | 'silver' | 'gold' | 'platinum' | null>(null)

  if (error && !p) return <div className="screen"><ErrorPlate message={error} onRetry={reload} /></div>
  if (!p) return <Loading />

  const top = maxIndex(p.ratingHistogram)
  const maxVal = Math.max(1, ...p.ratingHistogram)
  const ratingCount = p.ratingHistogram.reduce((a, b) => a + b, 0)
  const isMod = p.isMe && p.role !== 'user'

  const toggleFriend = async () => {
    setBusy(true)
    try {
      await api.toggleFriend(p.id, p.relation.following)
      haptic.select()
      reload()
    } catch {
      reload()
    } finally {
      setBusy(false)
    }
  }

  const friendLabel = p.relation.friends ? (
    <><CheckIcon />В друзьях</>
  ) : p.relation.following ? (
    <><CheckIcon />Вы подписаны</>
  ) : p.relation.follower ? (
    'Добавить в ответ'
  ) : (
    'Добавить в друзья'
  )

  const stats: { n: number; label: string; to: ProfileSection }[] = [
    { n: p.counts.marks, label: 'отметок', to: 'marked' },
    { n: p.counts.seen, label: 'просмотрено', to: 'seen' },
    { n: p.counts.friends, label: 'друзей', to: 'friends' },
  ]

  const medals: { key: 'bronze' | 'silver' | 'gold' | 'platinum'; label: string }[] = [
    { key: 'bronze', label: 'Бронза' },
    { key: 'silver', label: 'Серебро' },
    { key: 'gold', label: 'Золото' },
    { key: 'platinum', label: 'Платина' },
  ]

  const menu: { icon: IconName; label: string; to: ProfileSection; extra?: string; accent?: boolean; show: boolean }[] = [
    { icon: 'gear', label: 'Модерация клуба', to: 'club', accent: true, show: isMod },
    { icon: 'clock', label: 'Что уже смотрели', to: 'history', show: true },
    { icon: 'doc', label: 'Мои заявки', to: 'requests', show: true, extra: p.pendingRequests ? `${p.pendingRequests} на модерации` : undefined },
  ]

  return (
    <div className="screen" style={{ gap: 24 }}>
      <header className="row" style={{ gap: 14 }}>
        <span className="avatar">{p.avatarUrl ? <img src={p.avatarUrl} alt="" /> : p.name[0]}</span>
        <div className="stack" style={{ gap: 4 }}>
          <h1 className="h-screen">{p.name}</h1>
          <span className="small muted">{[p.username && `@${p.username}`, ROLE_LABEL[p.role]].filter(Boolean).join(' · ')}</span>
        </div>
      </header>

      {!p.isMe && (
        <button
          type="button"
          className={p.relation.following ? 'btn btn--white' : 'btn btn--primary'}
          style={{ minHeight: 44 }}
          aria-pressed={p.relation.following}
          disabled={busy}
          onClick={toggleFriend}
        >
          {friendLabel}
        </button>
      )}

      <div className="profile-top">
        <div className="stack">
          {stats.map((s) => (
            // В чужом профиле это просто числа: поимённый список желаемого
            // публичным быть не должен.
            <button key={s.to} type="button" className="stat-link" disabled={!p.isMe} onClick={() => onOpen(s.to)}>
              <span className="num">{s.n}</span>
              <span className="muted" style={{ flex: 1, fontSize: 14 }}>{s.label}</span>
              {p.isMe && <span style={{ color: 'var(--c-text-3)' }}>›</span>}
            </button>
          ))}
        </div>
        <section className="card stack" style={{ padding: 12, gap: 6, justifyContent: 'space-between' }}>
          <div className="section-head">
            <h2 className="h-section" style={{ fontSize: 12 }}>Как оценивает</h2>
            <span className="small muted">{ratingCount}</span>
          </div>
          <div className="stack" style={{ gap: 4 }}>
            <span className="sr-only">Чаще всего ставит {AXIS[top] ?? '—'}</span>
            <div className="histogram" aria-hidden="true">
              {p.ratingHistogram.map((v, i) => (
                <span key={i} data-max={i === top} style={{ height: `${(v / maxVal) * 100}%` }} />
              ))}
            </div>
            <div className="histogram-axis" aria-hidden="true">
              {AXIS.map((a, i) => (
                <span key={a} style={i === top ? { color: 'var(--c-accent)' } : undefined}>{a}</span>
              ))}
            </div>
          </div>
          {p.ratingAvg != null && (
            <span className="small muted">Средняя — <span style={{ color: 'var(--c-text)', fontWeight: 600 }}>{num(p.ratingAvg)}</span> из 5</span>
          )}
        </section>
      </div>

      <section className="stack" style={{ gap: 12 }}>
        <div className="row row--between">
          <h2 className="h-section">Любимое</h2>
          {p.isMe && (
            <button type="button" className="btn--text" style={{ height: 36, color: 'var(--c-accent)', fontWeight: 600, fontSize: 14 }} onClick={() => onOpen('favorites')}>
              Изменить
            </button>
          )}
        </div>
        <div className="grid-4">
          {p.favorites.map((f) => (
            <Poster key={f.id} film={f} width="100%" onClick={() => onOpenFilm(f.id)} />
          ))}
          {Array.from({ length: Math.max(0, 4 - p.favorites.length) }, (_, i) => (
            <button
              key={`slot-${i}`}
              type="button"
              aria-label="Добавить любимый фильм"
              disabled={!p.isMe}
              onClick={() => onOpen('favorites')}
              style={{ aspectRatio: '2 / 3', borderRadius: 'var(--r-s)', background: 'transparent', border: '1.5px dashed var(--c-line-strong)', color: 'var(--c-text-2)', fontSize: 24 }}
            >
              {p.isMe ? '+' : ''}
            </button>
          ))}
        </div>
      </section>

      <section className="stack" style={{ gap: 12 }}>
        <div className="section-head">
          <h2 className="h-section">Ачивки</h2>
          <span className="small muted">всего {p.achievements.total}</span>
        </div>
        <div className="grid-4">
          {medals.map((m) => {
            const n = p.achievements[m.key]
            return (
              <button
                key={m.key}
                type="button"
                className="cup"
                aria-pressed={tier === m.key}
                onClick={() => {
                  haptic.select()
                  setTier((t) => (t === m.key ? null : m.key))
                }}
                style={n ? undefined : { color: 'var(--c-text-3)' }}
              >
                <Trophy tier={m.key} size={34} muted={!n} />
                <span className="num" style={{ fontSize: 18 }}>{n}</span>
                <span className="xsmall" style={{ color: n ? 'var(--c-text-2)' : undefined, fontSize: 11 }}>{m.label}</span>
              </button>
            )
          })}
        </div>
        {tier ? (
          <div className="legacy stack" style={{ gap: 8, background: 'transparent' }}>
            <AchievementTierList data={p.raw.achievements} tier={tier} />
          </div>
        ) : (
          p.achievements.total === 0 && (
            <p className="small muted">
              {p.isMe ? 'Пока ни одной. Отметьте фильм просмотренным, поставьте оценку или придите на показ.' : 'Пока ни одной.'}
            </p>
          )
        )}
      </section>

      {p.attendance && (
        <section className="stack" style={{ gap: 12 }}>
          <h2 className="h-section">Ходит в клуб</h2>
          <div className="grid-2">
            {[
              [p.attendance.attended, plural(p.attendance.attended, ['посещение', 'посещения', 'посещений'])],
              [p.attendance.missed, plural(p.attendance.missed, ['пропуск', 'пропуска', 'пропусков'])],
            ].map(([n, label]) => (
              <div key={label} className="card tile">
                <span className="num tile__value">{n}</span>
                <span className="xsmall muted">{label}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {p.isMe && <nav className="menu" aria-label="Ещё">
        {menu.filter((m) => m.show).map((m) => (
          <button key={m.to} type="button" className="menu__item" onClick={() => onOpen(m.to)}>
            <span style={{ color: m.accent ? 'var(--c-accent)' : 'var(--c-text-2)', display: 'grid' }}>
              <Icon name={m.icon} size={20} />
            </span>
            <span className="menu__label" style={m.accent ? { fontWeight: 600 } : undefined}>{m.label}</span>
            {m.accent && <span className="role-tag">{ROLE_LABEL[p.role]}</span>}
            {m.extra && <span className="small muted">{m.extra}</span>}
            <span style={{ color: 'var(--c-text-3)' }}>›</span>
          </button>
        ))}
      </nav>}

      <p className="xsmall" style={{ color: 'var(--c-text-3)' }}>
        Данные о фильмах — TMDB. Этот продукт использует API TMDB, но не одобрен и не сертифицирован TMDB.
      </p>
    </div>
  )
}

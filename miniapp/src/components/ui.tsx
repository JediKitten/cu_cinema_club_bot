import type { ReactNode } from 'react'
import { Icon } from './Icon'
import type { TabId } from '../lib/types'
import { haptic } from '../lib/tg'

/* ---------- Таб-бар ---------- */

const TABS: { id: TabId; label: string; icon: 'catalog' | 'feed' | 'calendar' | 'user' }[] = [
  { id: 'catalog', label: 'Каталог', icon: 'catalog' },
  { id: 'feed', label: 'Лента', icon: 'feed' },
  { id: 'schedule', label: 'Расписание', icon: 'calendar' },
  { id: 'profile', label: 'Профиль', icon: 'user' },
]

export function TabBar({ active, onChange }: { active: TabId; onChange: (tab: TabId) => void }) {
  return (
    <nav className="tabbar" aria-label="Разделы">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          className="tabbar__item"
          aria-current={t.id === active ? 'page' : undefined}
          onClick={() => {
            if (t.id !== active) haptic.select()
            onChange(t.id)
          }}
        >
          <Icon name={t.icon} size={24} />
          {t.label}
        </button>
      ))}
    </nav>
  )
}

/* ---------- Заголовок экрана ---------- */

export function ScreenHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="screen-header">
      {children}
      <h1 className="h-screen">{title}</h1>
    </header>
  )
}

/* ---------- Состояния загрузки ---------- */

export function Loading({ text = 'Загрузка…' }: { text?: string }) {
  return <output className="state">{text}</output>
}

export function ErrorPlate({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-plate" role="alert">
      {message}
      {onRetry && (
        <>
          {' '}
          <button type="button" className="btn--text" style={{ color: 'inherit', textDecoration: 'underline' }} onClick={onRetry}>
            Повторить
          </button>
        </>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state">{children}</div>
}

/* ---------- Билет ---------- */

export function Ticket({
  variant,
  top,
  bottom,
}: {
  variant?: 'active' | 'past' | 'accent'
  top: ReactNode
  bottom: ReactNode
}) {
  return (
    <article className={`ticket${variant ? ` ticket--${variant}` : ''}`}>
      {top}
      <div className="ticket__perf" aria-hidden="true">
        <span className="ticket__notch ticket__notch--l" />
        <span className="ticket__notch ticket__notch--r" />
      </div>
      {bottom}
    </article>
  )
}

/* ---------- Чекбокс-строка ---------- */

export function CheckMark({ on }: { on: boolean }) {
  return <span className="checkbox">{on && <Icon name="check" size={16} strokeWidth={2.6} />}</span>
}

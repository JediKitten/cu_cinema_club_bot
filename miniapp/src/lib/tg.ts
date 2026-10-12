import { useEffect, useRef } from 'react'

/**
 * Тонкая обёртка над официальным Telegram WebApp SDK
 * (https://telegram.org/js/telegram-web-app.js подключён в index.html).
 * Кнопка «Назад», диалоги и вибрация — системные. Вне Telegram
 * (локальная разработка в браузере) используются простые заглушки.
 */

type HapticImpact = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'
type HapticNotice = 'error' | 'success' | 'warning'

interface TgWebApp {
  initData: string
  ready(): void
  expand(): void
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  setBottomBarColor?(color: string): void
  platform: string
  isVersionAtLeast(version: string): boolean
  requestFullscreen?(): void
  disableVerticalSwipes?(): void
  showAlert(message: string, cb?: () => void): void
  showConfirm(message: string, cb?: (ok: boolean) => void): void
  openLink(url: string): void
  openTelegramLink(url: string): void
  BackButton: {
    show(): void
    hide(): void
    onClick(cb: () => void): void
    offClick(cb: () => void): void
  }
  HapticFeedback: {
    impactOccurred(style: HapticImpact): void
    notificationOccurred(type: HapticNotice): void
    selectionChanged(): void
  }
}

// Глобальный window.Telegram уже описан в legacy/telegram.ts под его нужды;
// здесь читаем тот же объект через своё описание, не объявляя его второй раз.
const sdk = (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp
const wa: TgWebApp | undefined = sdk?.initData ? sdk : undefined

export const isTelegram = Boolean(wa)

/** Подпись для заголовка Authorization на бэкенде. */
export const initData: string = wa?.initData ?? ''

export function initTelegram(): void {
  if (!wa) return
  wa.ready()
  wa.expand()
  // Свайп вниз по ленте или списку не должен сворачивать приложение
  if (wa.isVersionAtLeast('7.7')) wa.disableVerticalSwipes?.()
  // На телефоне — на весь экран, без шапки Telegram. На компьютере
  // полноэкранное окно только мешает, там остаётся обычный вид.
  if (/^(ios|android)/.test(wa.platform) && wa.isVersionAtLeast('8.0')) {
    try {
      wa.requestFullscreen?.()
    } catch {
      // старый клиент — остаёмся в развёрнутом виде
    }
  }
  wa.setHeaderColor('#000000')
  wa.setBackgroundColor('#000000')
  wa.setBottomBarColor?.('#000000')
}

export const haptic = {
  /** Отметки, чекбоксы, звёзды */
  select: () => wa?.HapticFeedback.selectionChanged(),
  /** Свайп карточки */
  impact: (style: HapticImpact = 'light') => wa?.HapticFeedback.impactOccurred(style),
  /** Сохранение / ошибка */
  notify: (type: HapticNotice) => wa?.HapticFeedback.notificationOccurred(type),
}

export function tgConfirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (wa) wa.showConfirm(message, (ok) => resolve(ok))
    else resolve(window.confirm(message))
  })
}

export function tgAlert(message: string): Promise<void> {
  return new Promise((resolve) => {
    if (wa) wa.showAlert(message, () => resolve())
    else {
      window.alert(message)
      resolve()
    }
  })
}

export function openLink(url: string): void {
  if (wa) wa.openLink(url)
  else window.open(url, '_blank', 'noopener')
}

/**
 * Системная кнопка «Назад» Telegram. Единственный способ вернуться —
 * и из оверлеев, и из вложенных экранов (редизайн убрал текстовые «← Назад»).
 * Передайте `undefined`, чтобы скрыть кнопку.
 */
export function useBackButton(onBack: (() => void) | undefined): void {
  const ref = useRef(onBack)
  useEffect(() => {
    ref.current = onBack
  })
  const active = Boolean(onBack)
  useEffect(() => {
    if (!wa || !active) {
      wa?.BackButton.hide()
      return
    }
    const handler = () => ref.current?.()
    wa.BackButton.onClick(handler)
    wa.BackButton.show()
    return () => {
      wa.BackButton.offClick(handler)
      wa.BackButton.hide()
    }
  }, [active])
}

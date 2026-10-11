import type { Mark } from './types'

/**
 * Правила отметок — одинаковы в строке каталога, карточке фильма и ленте.
 *
 * | Сейчас          | Кнопки                              | Нажатие                                  |
 * |-----------------|-------------------------------------|------------------------------------------|
 * | none            | «Желаемое», «Ближайшее»             | ставит отметку                           |
 * | wish            | «✓ Желаемое», «Ближайшее»           | 1-я снимает, 2-я переключает в soon       |
 * | soon            | только «✓ Ближайшее»                | снимает                                  |
 * | wish_expired    | «✓ Желаемое», «Снова в ближайшее»   | 2-я продлевает «Ближайшее» на 2 недели    |
 */

export type MarkAction = 'wish' | 'soon'

export function nextMark(current: Mark, action: MarkAction): Mark {
  if (action === 'wish') {
    if (current === 'none') return 'wish'
    if (current === 'wish' || current === 'wish_expired') return 'none'
    return current // у soon кнопки «Желаемое» нет
  }
  return current === 'soon' ? 'none' : 'soon'
}

export interface MarkButtonState {
  visible: boolean
  pressed: boolean
  label: string
}

export type MarkSize = 'row' | 'card'

const LABELS = {
  row: { wish: 'Желаемое', soon: 'Ближайшее', renew: 'Снова в ближайшее' },
  card: { wish: 'Хочу посмотреть', soon: 'Готов в ближайшие 2 недели', renew: 'Снова в ближайшие 2 недели' },
} as const

export function markButtons(current: Mark, size: MarkSize = 'row'): { wish: MarkButtonState; soon: MarkButtonState } {
  const l = LABELS[size]
  return {
    wish: {
      visible: current !== 'soon',
      pressed: current === 'wish' || current === 'wish_expired',
      label: l.wish,
    },
    soon: {
      visible: true,
      pressed: current === 'soon',
      label: current === 'wish_expired' ? l.renew : l.soon,
    },
  }
}

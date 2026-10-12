import type { Mark } from './types'

/**
 * Правила отметок — одинаковы в строке каталога, карточке фильма и ленте.
 * Обе кнопки видны всегда: состояния взаимоисключающие, и нажатие на
 * вторую переключает отметку, а не прячет первую.
 *
 * | Сейчас          | Кнопки                              | Нажатие                                  |
 * |-----------------|-------------------------------------|------------------------------------------|
 * | none            | «Желаемое», «Ближайшее»             | ставит отметку                           |
 * | wish            | «✓ Желаемое», «Ближайшее»           | 1-я снимает, 2-я переключает в soon      |
 * | soon            | «Желаемое», «✓ Ближайшее»           | 1-я переключает в wish, 2-я снимает      |
 * | wish_expired    | «✓ Желаемое», «↻ Ближайшее»         | 2-я продлевает «Ближайшее» на 2 недели   |
 */

export type MarkAction = 'wish' | 'soon'

export function nextMark(current: Mark, action: MarkAction): Mark {
  if (action === 'wish') {
    if (current === 'none') return 'wish'
    if (current === 'wish' || current === 'wish_expired') return 'none'
    return 'wish' // из soon — переключение
  }
  return current === 'soon' ? 'none' : 'soon'
}

export interface MarkButtonState {
  pressed: boolean
  label: string
  /** Кнопка продлевает истёкшее «Ближайшее», а не ставит его */
  renew?: boolean
}

export function markButtons(current: Mark): { wish: MarkButtonState; soon: MarkButtonState } {
  return {
    wish: {
      pressed: current === 'wish' || current === 'wish_expired',
      label: 'Желаемое',
    },
    soon: {
      pressed: current === 'soon',
      label: 'Ближайшее',
      renew: current === 'wish_expired',
    },
  }
}

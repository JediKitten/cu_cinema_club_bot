import { describe, expect, it } from 'vitest'
import { markButtons, nextMark } from './marks'

describe('nextMark', () => {
  it('ставит отметку с нуля', () => {
    expect(nextMark('none', 'wish')).toBe('wish')
    expect(nextMark('none', 'soon')).toBe('soon')
  })
  it('из «Желаемого»: первая кнопка снимает, вторая переключает', () => {
    expect(nextMark('wish', 'wish')).toBe('none')
    expect(nextMark('wish', 'soon')).toBe('soon')
  })
  it('«Ближайшее» снимается повторным нажатием', () => {
    expect(nextMark('soon', 'soon')).toBe('none')
  })
  it('истёкшее «Ближайшее» продлевается', () => {
    expect(nextMark('wish_expired', 'soon')).toBe('soon')
    expect(nextMark('wish_expired', 'wish')).toBe('none')
  })
})

describe('markButtons', () => {
  it('при «Ближайшем» видна только одна кнопка', () => {
    const b = markButtons('soon')
    expect(b.wish.visible).toBe(false)
    expect(b.soon).toMatchObject({ visible: true, pressed: true, label: 'Ближайшее' })
  })
  it('истёкшее показывает «Снова в ближайшее»', () => {
    const b = markButtons('wish_expired')
    expect(b.wish.pressed).toBe(true)
    expect(b.soon.label).toBe('Снова в ближайшее')
  })
  it('в карточке — полные подписи', () => {
    const b = markButtons('none', 'card')
    expect(b.wish.label).toBe('Хочу посмотреть')
    expect(b.soon.label).toBe('Готов в ближайшие 2 недели')
  })
})

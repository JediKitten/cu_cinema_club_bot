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
  it('из «Ближайшего»: вторая снимает, первая переключает в «Желаемое»', () => {
    expect(nextMark('soon', 'soon')).toBe('none')
    expect(nextMark('soon', 'wish')).toBe('wish')
  })
  it('истёкшее «Ближайшее» продлевается', () => {
    expect(nextMark('wish_expired', 'soon')).toBe('soon')
    expect(nextMark('wish_expired', 'wish')).toBe('none')
  })
})

describe('markButtons', () => {
  it('при «Ближайшем» обе кнопки на месте, нажата вторая', () => {
    const b = markButtons('soon')
    expect(b.wish).toMatchObject({ pressed: false, label: 'Желаемое' })
    expect(b.soon).toMatchObject({ pressed: true, label: 'Ближайшее' })
  })
  it('истёкшее предлагает продлить «Ближайшее»', () => {
    const b = markButtons('wish_expired')
    expect(b.wish.pressed).toBe(true)
    expect(b.soon).toMatchObject({ pressed: false, renew: true, label: 'Ближайшее' })
  })
})

import { describe, expect, it } from 'vitest'
import { eveningDate, maxIndex, num, plural, runtime, showDate, starFills, weekRange } from './format'

describe('format', () => {
  it('дата показа по Москве', () => {
    expect(showDate('2026-10-10T16:00:00Z')).toEqual({ day: 'Сб 10 окт', time: '19:00' })
  })
  it('вечер в бюллетене', () => {
    expect(eveningDate('2026-10-14T19:00:00+03:00')).toEqual({ weekday: 'Ср', text: '14 октября, 19:00' })
  })
  it('диапазон недели', () => {
    expect(weekRange('2026-10-12')).toBe('12–18 октября')
    expect(weekRange('2026-09-28')).toBe('28 сентября – 4 октября')
  })
  it('числа и склонения', () => {
    expect(num(4.6)).toBe('4,6')
    expect(plural(1, ['оценка', 'оценки', 'оценок'])).toBe('оценка')
    expect(plural(3, ['оценка', 'оценки', 'оценок'])).toBe('оценки')
    expect(plural(11, ['оценка', 'оценки', 'оценок'])).toBe('оценок')
    expect(runtime(169)).toBe('2 ч 49 мин')
    expect(runtime(120)).toBe('2 ч')
  })
  it('звёзды с половинками', () => {
    expect(starFills(3.5)).toEqual(['full', 'full', 'full', 'half', 'empty'])
    expect(starFills(undefined)).toEqual(['empty', 'empty', 'empty', 'empty', 'empty'])
  })
  it('максимум гистограммы', () => {
    expect(maxIndex([1, 5, 3])).toBe(1)
    expect(maxIndex([0, 0])).toBe(-1)
  })
})

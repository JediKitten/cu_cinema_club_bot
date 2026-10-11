const TZ = 'Europe/Moscow'
const WEEKDAYS = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']

interface Parts { y: number; m: number; d: number; wd: number; hh: string; mm: string }

/** Части даты по московскому времени — клуб живёт по Москве. */
export function moscowParts(iso: string): Parts {
  const date = new Date(iso)
  const f = new Intl.DateTimeFormat('en-GB', {
    timeZone: TZ, year: 'numeric', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23',
  })
  const p = Object.fromEntries(f.formatToParts(date).map((x) => [x.type, x.value]))
  const wdIndex = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(p.weekday)
  return { y: +p.year, m: +p.month - 1, d: +p.day, wd: wdIndex, hh: p.hour, mm: p.minute }
}

/** «Сб 10 окт» + «19:00» — для билета показа. */
export function showDate(iso: string): { day: string; time: string } {
  const p = moscowParts(iso)
  return { day: `${WEEKDAYS[p.wd]} ${p.d} ${MONTHS_SHORT[p.m]}`, time: `${p.hh}:${p.mm}` }
}

/** «14 октября, 19:00» — для вечера в бюллетене. */
export function eveningDate(iso: string): { weekday: string; text: string } {
  const p = moscowParts(iso)
  return { weekday: WEEKDAYS[p.wd], text: `${p.d} ${MONTHS_GEN[p.m]}, ${p.hh}:${p.mm}` }
}

/** «12–18 октября» или «28 сентября – 4 октября». weekStart — ISO-дата понедельника. */
export function weekRange(weekStart: string): string {
  const start = new Date(`${weekStart}T12:00:00Z`)
  const end = new Date(start.getTime() + 6 * 86400000)
  const sm = start.getUTCMonth()
  const em = end.getUTCMonth()
  return sm === em
    ? `${start.getUTCDate()}–${end.getUTCDate()} ${MONTHS_GEN[em]}`
    : `${start.getUTCDate()} ${MONTHS_GEN[sm]} – ${end.getUTCDate()} ${MONTHS_GEN[em]}`
}

/** 4.5 → «4,5»; 8 → «8,0» при digits=1. */
export function num(value: number, digits = 1): string {
  return value.toFixed(digits).replace('.', ',')
}

/** Склонение: plural(3, ['оценка','оценки','оценок']) → «оценки». */
export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100
  const b = a % 10
  if (a > 10 && a < 20) return forms[2]
  if (b > 1 && b < 5) return forms[1]
  if (b === 1) return forms[0]
  return forms[2]
}

/** «2 ч 49 мин» */
export function runtime(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  if (!h) return `${m} мин`
  return m ? `${h} ч ${m} мин` : `${h} ч`
}

/** Состояние одной звезды для значения 0–5 с половинками. */
export type StarFill = 'full' | 'half' | 'empty'
export function starFills(value: number | undefined): StarFill[] {
  const v = value ?? 0
  return [1, 2, 3, 4, 5].map((i) => (v >= i ? 'full' : v >= i - 0.5 ? 'half' : 'empty'))
}

/** Индекс самой высокой корзины гистограммы (-1, если пусто). */
export function maxIndex(values: number[]): number {
  let idx = -1
  let max = 0
  values.forEach((v, i) => {
    if (v > max) { max = v; idx = i }
  })
  return idx
}

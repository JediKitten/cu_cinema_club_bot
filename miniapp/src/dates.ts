/** Форматирование дат в локальной зоне пользователя.
 *
 * С сервера времена приходят в UTC (ISO с суффиксом Z), браузер сам переводит
 * их в зону устройства — нам остаётся только выбрать формат.
 */

const WEEKDAYS = [
  "воскресенье",
  "понедельник",
  "вторник",
  "среда",
  "четверг",
  "пятница",
  "суббота",
];

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function weekdayName(iso: string): string {
  return WEEKDAYS[new Date(iso).getDay()];
}

/** «понедельник, 8 сентября» */
export function dayLabel(iso: string): string {
  const date = new Date(iso);
  return `${weekdayName(iso)}, ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

/** «19:00» */
export function timeLabel(iso: string): string {
  const date = new Date(iso);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** «8–14 сентября» — заголовок недели показов. */
export function weekLabel(weekStartIso: string): string {
  const start = new Date(`${weekStartIso}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);

  const sameMonth = start.getMonth() === end.getMonth();
  const left = sameMonth ? `${start.getDate()}` : `${start.getDate()} ${MONTHS[start.getMonth()]}`;
  return `${left}–${end.getDate()} ${MONTHS[end.getMonth()]}`;
}

/** Короткая подпись «до пятницы» / «сегодня» для дедлайнов. */
export function shortDay(iso: string): string {
  const date = new Date(iso);
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

const WEEKDAYS_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

/** «пн» — для заголовков колонок матрицы, где места мало. */
export function weekdayShort(iso: string): string {
  return WEEKDAYS_SHORT[new Date(iso).getDay()];
}

/** Сдвиг на неделю: «2026-09-14» → «2026-09-21».
 *
 * Считаем через UTC-полночь: локальная полночь в дни перехода на летнее время
 * сдвигается, и прибавление 7×24 часов может дать субботу или воскресенье.
 */
export function shiftWeek(weekStartIso: string, weeks: number): string {
  const date = new Date(`${weekStartIso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + weeks * 7);
  return date.toISOString().slice(0, 10);
}

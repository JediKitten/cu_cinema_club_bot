"""Показ в календарь — файлом .ics (RFC 5545).

Напоминания бота приходят за сутки и за два часа, но вечер всё равно
забывают: его не видно там, где человек планирует неделю. Файл .ics
открывается штатным календарём телефона и ставит событие туда.

Формат пишется руками: одно событие — два десятка строк, и библиотека
ради них была бы тяжелее самого кода. Три правила формата, которые легко
нарушить, собраны здесь: строки через CRLF, текст с экранированными
`\\ ; ,` и переводами строк, и строки не длиннее 75 октетов.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# Напоминание в самом событии: календарь покажет его, даже если бот
# человек давно замьютил.
ALARM_BEFORE = timedelta(hours=2)

LINE_LIMIT = 75


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    uid: str
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str | None = None
    description: str | None = None
    url: str | None = None


def escape_text(value: str) -> str:
    """Экранирование TEXT по RFC 5545 §3.3.11."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Перенос длинной строки: не больше 75 октетов, продолжение — с пробела.

    Считаются именно октеты UTF-8, а не символы: кириллица — два байта на
    букву, и строка «в 75 символов» оказалась бы вдвое длиннее допустимого.
    Разрезать посреди многобайтного символа нельзя — режем по символам.
    """
    parts: list[str] = []
    current = ""
    limit = LINE_LIMIT
    for char in line:
        if len((current + char).encode()) > limit:
            parts.append(current)
            current = char
            # У строк-продолжений первый октет — пробел, он тоже в счёт.
            limit = LINE_LIMIT - 1
        else:
            current += char
    parts.append(current)
    return "\r\n ".join(parts)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render(event: CalendarEvent, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kinoklub//Screenings//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        # UID постоянный у показа: скачал заново после переноса — календарь
        # обновит событие, а не заведёт второе рядом со старым.
        f"UID:{event.uid}",
        f"DTSTAMP:{_stamp(now)}",
        # Номер правки растёт со временем: по нему календарь понимает, что
        # файл новее того, что у него уже есть.
        f"SEQUENCE:{int(now.timestamp()) // 60}",
        f"DTSTART:{_stamp(event.starts_at)}",
        f"DTEND:{_stamp(event.ends_at)}",
        f"SUMMARY:{escape_text(event.title)}",
    ]
    if event.location:
        lines.append(f"LOCATION:{escape_text(event.location)}")
    if event.description:
        lines.append(f"DESCRIPTION:{escape_text(event.description)}")
    if event.url:
        lines.append(f"URL:{event.url}")
    lines += [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"TRIGGER:-PT{int(ALARM_BEFORE.total_seconds() // 60)}M",
        f"DESCRIPTION:{escape_text(event.title)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "".join(fold(line) + "\r\n" for line in lines)

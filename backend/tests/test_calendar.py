"""Показ в календарь файлом .ics."""

from datetime import UTC, datetime, timedelta

from app.services import calendar
from app.services import schedule as sched
from tests.test_schedule import voted_round

EVENT = calendar.CalendarEvent(
    uid="screening-7@cinema-club",
    title="Киноклуб: Остров проклятых, 2010; режиссёр — Скорсезе",
    starts_at=datetime(2026, 9, 25, 16, 0, tzinfo=UTC),
    ends_at=datetime(2026, 9, 25, 19, 0, tzinfo=UTC),
    location="Аудитория 101",
    description="Показ на английском.\nЕсли планы изменятся — отмените запись.",
)


def test_lines_end_with_crlf_and_fit_in_75_octets():
    text = calendar.render(EVENT)
    assert text.endswith("\r\n")
    lines = text.split("\r\n")[:-1]
    # Кириллица — по два байта на букву: считать надо октеты, а не символы.
    assert all(len(line.encode()) <= 75 for line in lines)
    # Разрезанное собирается обратно в исходное без потерь.
    unfolded = text.replace("\r\n ", "")
    assert r"SUMMARY:Киноклуб: Остров проклятых\, 2010\; режиссёр — Скорсезе" in unfolded


def test_text_is_escaped():
    unfolded = calendar.render(EVENT).replace("\r\n ", "")
    assert "DESCRIPTION:Показ на английском.\\nЕсли планы изменятся" in unfolded
    assert calendar.escape_text("a\\b") == "a\\\\b"


def test_event_has_stable_uid_times_and_alarm():
    text = calendar.render(EVENT, now=datetime(2026, 9, 22, tzinfo=UTC))
    assert "UID:screening-7@cinema-club" in text
    assert "DTSTART:20260925T160000Z" in text and "DTEND:20260925T190000Z" in text
    assert "BEGIN:VALARM" in text and "TRIGGER:-PT120M" in text


async def test_file_for_a_published_screening(client, session):
    round_, films, slots, boss, _ = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)

    # До публикации расписания показ не видит никто, кроме составителей —
    # и файл по его номеру не должен его выдавать.
    hidden = await client.get(f"/api/schedule/screenings/{screening.id}/calendar.ics")
    assert hidden.status_code == 404

    await sched.publish_schedule(session, round_, boss.id)
    response = await client.get(f"/api/schedule/screenings/{screening.id}/calendar.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text.replace("\r\n ", "")
    assert f"UID:screening-{screening.id}@cinema-club" in body
    assert films[0].title_ru in body


async def test_cancelled_screening_has_no_file(client, session):
    round_, films, slots, boss, _ = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.cancel_screening(session, screening.id, "Проектор сломался", boss.id)

    response = await client.get(f"/api/schedule/screenings/{screening.id}/calendar.ics")
    assert response.status_code == 404


def test_duration_comes_from_the_slot():
    starts = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)
    event = calendar.CalendarEvent("u", "t", starts, starts + timedelta(minutes=150))
    assert "DTEND:20260925T183000Z" in calendar.render(event)

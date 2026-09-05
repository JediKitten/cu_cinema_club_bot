"""Этап 4: код присутствия, отметка, обратная связь (§8)."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Attendance, Feedback, Interest, Slot, Watch
from app.models.enums import AttendanceMethod, InterestKind, RevokeReason
from app.services import attendance as att
from app.services import interests as marks
from app.services import schedule as sched
from app.services.attendance import AttendanceError
from tests.test_schedule import voted_round
from tests.test_weights import make_user

ROTATION = 60
WINDOW = 20


async def running_screening(session, capacity: int = 40):
    """Показ, который уже начался: окно отметки открыто."""
    round_, films, slots, boss, voters = await voted_round(session, capacity)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    for voter in voters:
        await sched.confirm(session, screening.id, voter.id)

    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) - timedelta(minutes=5)
    await session.commit()
    return round_, films, screening, boss, voters


async def test_code_rotates_and_is_not_stored(session):
    _, _, screening, _, _ = await running_screening(session)

    now = datetime.now(UTC)
    first = await att.current_code(session, screening, ROTATION, now)
    same = await att.current_code(session, screening, ROTATION, now)
    later = await att.current_code(session, screening, ROTATION, now + timedelta(seconds=ROTATION))

    assert first.code == same.code
    assert first.code != later.code
    assert len(first.code) == 6 and first.code.isdigit()

    # В базе лежит секрет, а не код: украсть готовый код неоткуда.
    assert screening.attendance_secret
    assert first.code not in screening.attendance_secret


async def test_previous_code_still_accepted(session):
    """Иначе начавший ввод за секунду до смены получал бы отказ без объяснений."""
    _, _, screening, _, voters = await running_screening(session)

    now = datetime.now(UTC)
    old = await att.current_code(session, screening, ROTATION, now - timedelta(seconds=ROTATION))

    marked = await att.mark_by_code(
        session, screening.id, voters[0].id, old.code, ROTATION, WINDOW, now
    )
    assert marked.method == AttendanceMethod.CODE


async def test_stale_code_rejected(session):
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    ancient = await att.current_code(
        session, screening, ROTATION, now - timedelta(seconds=ROTATION * 5)
    )

    with pytest.raises(AttendanceError, match="сменился"):
        await att.mark_by_code(
            session, screening.id, voters[0].id, ancient.code, ROTATION, WINDOW, now
        )


async def test_code_only_works_inside_the_window(session):
    _, _, screening, _, voters = await running_screening(session)

    # Сдвигаем сеанс так, чтобы окно уже закрылось.
    slot = await session.get(Slot, screening.slot_id)
    slot.starts_at = datetime.now(UTC) - timedelta(hours=3)
    await session.commit()

    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    with pytest.raises(AttendanceError, match="первые минуты"):
        await att.mark_by_code(
            session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now
        )


async def test_code_before_start_rejected(session):
    _, _, screening, _, voters = await running_screening(session)
    slot = await session.get(Slot, screening.slot_id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()

    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    with pytest.raises(AttendanceError, match="первые минуты"):
        await att.mark_by_code(
            session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now
        )


async def test_code_rejected_from_someone_who_did_not_confirm(session):
    """Код легко переслать, поэтому подтверждение — обязательное условие (§8)."""
    _, _, screening, _, _ = await running_screening(session)
    stranger = await make_user(session, "Не записывался")
    await session.commit()

    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    with pytest.raises(AttendanceError, match="не подтверждали"):
        await att.mark_by_code(
            session, screening.id, stranger.id, code.code, ROTATION, WINDOW, now
        )


async def test_moderator_can_add_anyone_by_hand(session):
    _, _, screening, boss, _ = await running_screening(session)
    stranger = await make_user(session, "Пришёл без записи")
    await session.commit()

    marked = await att.mark_manually(session, screening.id, stranger.id, boss.id)
    assert marked.method == AttendanceMethod.MANUAL
    assert marked.marked_by == boss.id


async def test_attendance_is_idempotent(session):
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)

    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    total = await session.scalar(sa.select(sa.func.count()).select_from(Attendance))
    assert total == 1


async def test_coming_moves_film_to_watched_and_drops_the_mark(session):
    """Пришёл — отметка снимается, фильм уходит в «Просмотренные» (§8)."""
    _, films, screening, _, voters = await running_screening(session)
    viewer = voters[0]
    await marks.set_mark(session, viewer.id, films[0].id, InterestKind.SOON, 14, 10)

    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, viewer.id, code.code, ROTATION, WINDOW, now)

    interest = (
        await session.execute(
            sa.select(Interest).where(
                Interest.user_id == viewer.id, Interest.film_id == films[0].id
            )
        )
    ).scalar_one()
    assert interest.revoked_at is not None
    assert interest.revoke_reason == RevokeReason.WATCHED

    watch = (
        await session.execute(
            sa.select(Watch).where(Watch.user_id == viewer.id, Watch.film_id == films[0].id)
        )
    ).scalar_one()
    assert watch.source == "attendance"


async def test_absentees_keep_their_marks(session):
    """У тех, кто не пришёл, отметки не трогаются (§8)."""
    _, films, screening, _, voters = await running_screening(session)
    absent = voters[1]
    await marks.set_mark(session, absent.id, films[0].id, InterestKind.SOON, 14, 10)

    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    state = await marks.state(session, absent.id, films[0].id, 14)
    assert state.effective_kind == InterestKind.SOON


async def test_feedback_requires_attendance(session):
    _, _, screening, _, voters = await running_screening(session)

    with pytest.raises(AttendanceError, match="на котором были"):
        await att.save_feedback(session, screening.id, voters[0].id, 8, None, None)


async def test_feedback_saved_and_editable(session):
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    await att.save_feedback(
        session, screening.id, voters[0].id, 9, "Отлично", {"sound": 4, "comment": "тихо"}
    )
    again = await att.save_feedback(session, screening.id, voters[0].id, 7, None, None)

    assert again.film_rating == 7
    assert again.review_text is None
    assert await session.scalar(sa.select(sa.func.count()).select_from(Feedback)) == 1


async def test_rating_bounds_checked(session):
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    with pytest.raises(AttendanceError, match="от 1 до 10"):
        await att.save_feedback(session, screening.id, voters[0].id, 11, None, None)


async def test_org_rating_is_separate_from_the_film(session):
    """Плохая проекция не должна топить хорошее кино (§8)."""
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    feedback = await att.save_feedback(
        session, screening.id, voters[0].id, 10, None, {"sound": 1, "picture": 2}
    )
    assert feedback.film_rating == 10
    assert feedback.org_sound == 1
    assert feedback.org_picture == 2


async def test_attendees_list_is_ordered(session):
    _, _, screening, boss, voters = await running_screening(session)
    for voter in voters:
        await att.mark_manually(session, screening.id, voter.id, boss.id)

    listed = await att.attendees(session, screening.id)
    assert [a.user_id for a in listed] == [v.id for v in voters]

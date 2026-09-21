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
from tests.conftest import login
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
        await att.save_feedback(session, screening.id, voters[0].id, 8, None)


async def test_feedback_saved_and_editable(session):
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    await att.save_feedback(
        session, screening.id, voters[0].id, 9, "Отлично", visit_rating=10
    )
    again = await att.save_feedback(session, screening.id, voters[0].id, 7, None)

    assert again.film_rating == 7
    assert again.review_text is None
    assert await session.scalar(sa.select(sa.func.count()).select_from(Feedback)) == 1


async def test_rating_bounds_checked(session):
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    with pytest.raises(AttendanceError, match="от 1 до 10"):
        await att.save_feedback(session, screening.id, voters[0].id, 11, None)


async def test_visit_and_discussion_are_separate_from_the_film(session):
    """Плохой вечер не должен топить хорошее кино (§8): оценки живут врозь."""
    _, _, screening, _, voters = await running_screening(session)
    now = datetime.now(UTC)
    code = await att.current_code(session, screening, ROTATION, now)
    await att.mark_by_code(session, screening.id, voters[0].id, code.code, ROTATION, WINDOW, now)

    feedback = await att.save_feedback(
        session, screening.id, voters[0].id, 10, None, visit_rating=3, discussion_rating=4
    )
    assert feedback.film_rating == 10
    assert (feedback.visit_rating, feedback.discussion_rating) == (3, 4)
    # В рейтинг фильма ушла только оценка фильма.
    from app.services import ratings

    assert await ratings.my_rating(session, voters[0].id, screening.film_id) == 5.0


async def test_discussion_answer_is_one_of_three(session):
    """Оценка, «не был» или «затрудняюсь» — но не оценка и причина разом."""
    _, _, screening, boss, voters = await running_screening(session)
    await att.mark_manually(session, screening.id, voters[0].id, boss.id)

    skipped = await att.save_feedback(
        session, screening.id, voters[0].id, None, None, discussion_skip="absent"
    )
    assert skipped.discussion_skip == "absent" and skipped.discussion_rating is None

    with pytest.raises(AttendanceError, match="либо оценка"):
        await att.save_feedback(
            session, screening.id, voters[0].id, None, None,
            discussion_rating=8, discussion_skip="unsure",
        )
    with pytest.raises(AttendanceError, match="Непонятный ответ"):
        await att.save_feedback(
            session, screening.id, voters[0].id, None, None, discussion_skip="пропустил"
        )


async def test_attendees_list_is_ordered(session):
    _, _, screening, boss, voters = await running_screening(session)
    for voter in voters:
        await att.mark_manually(session, screening.id, voter.id, boss.id)

    listed = await att.attendees(session, screening.id)
    assert [a.user_id for a in listed] == [v.id for v in voters]


async def test_film_question_disappears_once_the_film_is_rated(session, client):
    """Оценка у фильма одна, откуда бы ни пришла. Поставивший её в каталоге
    не должен объяснять то же самое второй раз — форма просто не спрашивает."""
    from app.services import ratings
    
    _, _, screening, boss, voters = await running_screening(session)
    await att.mark_manually(session, screening.id, voters[0].id, boss.id)
    await session.commit()

    auth = await login(client, voters[0].tg_id, voters[0].display_name)
    headers = {"Authorization": f"Bearer {auth['token']}"}

    before = (await client.get(f"/api/screenings/{screening.id}/feedback", headers=headers)).json()
    assert before["film_already_rated"] is False

    await ratings.set_rating(session, voters[0].id, screening.film_id, 4.5)
    after = (await client.get(f"/api/screenings/{screening.id}/feedback", headers=headers)).json()
    assert after["film_already_rated"] is True


async def test_survey_answers_go_through_the_api(session, client):
    _, _, screening, boss, voters = await running_screening(session)
    await att.mark_manually(session, screening.id, voters[0].id, boss.id)
    await session.commit()

    auth = await login(client, voters[0].tg_id, voters[0].display_name)
    saved = await client.put(
        f"/api/screenings/{screening.id}/feedback",
        json={
            "visit_rating": 9,
            "film_rating": 8,
            "discussion_skip": "unsure",
            "review_text": "Стулья жёсткие",
        },
        headers={"Authorization": f"Bearer {auth['token']}"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["visit_rating"] == 9
    assert body["discussion_skip"] == "unsure"
    assert body["review_text"] == "Стулья жёсткие"
    # Оценка фильма из формы — та же, что в каталоге.
    assert body["film_already_rated"] is True

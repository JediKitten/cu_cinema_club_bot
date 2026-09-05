"""Пригласительные ссылки на конкретный фильм."""

import pytest
import sqlalchemy as sa

from app.models import Referral
from app.models.enums import InterestKind
from app.services import interests as marks
from app.services import referrals
from tests.test_weights import make_film, make_user


def test_payload_roundtrip():
    assert referrals.parse_payload(referrals.make_payload(12, 7)) == (12, 7)


def test_payload_fits_telegram_charset():
    """Telegram принимает в start только латиницу, цифры, «_» и «-»."""
    payload = referrals.make_payload(999999, 123456)
    assert payload.replace("_", "").replace("-", "").isalnum()
    assert len(payload) <= 64


@pytest.mark.parametrize("bad", ["", "hello", "f12", "r7", "f12r", "fXrY", "f12r7extra"])
def test_broken_payload_rejected(bad):
    assert referrals.parse_payload(bad) is None


def test_link_points_at_the_bot():
    link = referrals.invite_link("cu_cinema_club_bot", 5, 3)
    assert link == "https://t.me/cu_cinema_club_bot?start=f5r3"


async def test_referral_recorded_once(session):
    inviter = await make_user(session, "Позвал")
    guest = await make_user(session, "Пришёл")
    film = await make_film(session, "Фильм")
    await session.commit()

    assert await referrals.record(session, inviter.id, guest.id, film.id) is True
    # Повторный переход по той же ссылке не должен накручивать счётчик.
    assert await referrals.record(session, inviter.id, guest.id, film.id) is False
    assert await session.scalar(sa.select(sa.func.count()).select_from(Referral)) == 1


async def test_cannot_invite_yourself(session):
    user = await make_user(session, "Хитрый")
    film = await make_film(session, "Фильм")
    await session.commit()

    assert await referrals.record(session, user.id, user.id, film.id) is False
    assert await session.scalar(sa.select(sa.func.count()).select_from(Referral)) == 0


async def test_first_inviter_keeps_the_credit(session):
    """За одного человека на одном фильме не должны спорить двое."""
    first = await make_user(session, "Первый")
    second = await make_user(session, "Второй")
    guest = await make_user(session, "Гость")
    film = await make_film(session, "Фильм")
    await session.commit()

    assert await referrals.record(session, first.id, guest.id, film.id) is True
    assert await referrals.record(session, second.id, guest.id, film.id) is False

    assert (await referrals.stats(session, first.id)).invited == 1
    assert (await referrals.stats(session, second.id)).invited == 0


async def test_acceptance_counted_only_after_the_visit(session):
    """Если человек уже держал фильм в списках, приглашение ни при чём."""
    inviter = await make_user(session, "Позвал")
    early = await make_user(session, "Уже хотел")
    later = await make_user(session, "Согласился")
    film = await make_film(session, "Фильм")
    await session.commit()

    # Первый отметил фильм ещё до приглашения.
    await marks.set_mark(session, early.id, film.id, InterestKind.WISHLIST, 14, 10)
    await referrals.record(session, inviter.id, early.id, film.id)

    # Второй — после.
    await referrals.record(session, inviter.id, later.id, film.id)
    await marks.set_mark(session, later.id, film.id, InterestKind.SOON, 14, 10)

    counts = await referrals.stats(session, inviter.id)
    assert counts.invited == 2
    assert counts.accepted == 1


async def test_no_automatic_vote(session):
    """Переход по ссылке сам по себе голоса не ставит."""
    inviter = await make_user(session, "Позвал")
    guest = await make_user(session, "Пришёл")
    film = await make_film(session, "Фильм")
    await session.commit()

    await referrals.record(session, inviter.id, guest.id, film.id)

    state = await marks.state(session, guest.id, film.id, 14)
    assert state.effective_kind is None
    assert (await referrals.stats(session, inviter.id)).accepted == 0


async def test_card_knows_who_invited(session):
    inviter = await make_user(session, "Кир")
    guest = await make_user(session, "Гость")
    film = await make_film(session, "Фильм")
    await session.commit()
    await referrals.record(session, inviter.id, guest.id, film.id)

    found = await referrals.pending_invite(session, guest.id, film.id)
    assert found is not None and found.display_name == "Кир"
    assert await referrals.pending_invite(session, inviter.id, film.id) is None


async def test_unknown_referrer_or_film_ignored(session):
    guest = await make_user(session, "Гость")
    film = await make_film(session, "Фильм")
    await session.commit()

    assert await referrals.record(session, 99999, guest.id, film.id) is False
    assert await referrals.record(session, guest.id, guest.id, 99999) is False

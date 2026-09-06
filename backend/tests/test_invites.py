"""Закрытая бета: вход по кодам-приглашениям (расширение по просьбе клуба)."""

import pytest
import sqlalchemy as sa

from app.models import InviteCode, Notification, User
from app.models.enums import UserRole
from app.services import invites
from app.services.invites import InviteError
from app.services.settings import SettingsService
from tests.conftest import SUPERADMIN_TG_ID, login
from tests.test_weights import make_user


async def beta_on(session) -> None:
    await SettingsService(session).set_many({"beta_invite_required": True}, None)
    await session.commit()


async def admin(session) -> User:
    user = await make_user(session, "Админ")
    user.role = UserRole.ADMIN
    user.access_granted_at = sa.func.now()
    await session.commit()
    return user


def test_code_normalization_forgives_how_people_type():
    """Код диктуют вслух и переписывают с экрана — регистр и дефисы не значат ничего."""
    assert invites.normalize(" ab-cd 12 ") == "ABCD12"
    assert invites.normalize("") == ""


def test_generated_codes_avoid_lookalike_characters():
    """Ноль и «O», единица и «I» — самая частая причина «код не подходит»."""
    for _ in range(50):
        code = invites.generate()
        assert len(code) == invites.LENGTH
        assert not set(code) & set("O0I1")


async def test_code_grants_access_and_is_counted(session):
    await beta_on(session)
    boss = await admin(session)
    code = await invites.create(session, boss.id, max_activations=2)

    first = await make_user(session, "Первый")
    second = await make_user(session, "Второй")
    await session.commit()

    assert invites.has_access(first, beta=True) is False
    await invites.redeem(session, first, code.code.lower())
    assert invites.has_access(first, beta=True) is True
    assert first.invite_code_id == code.id

    await invites.redeem(session, second, code.code)

    view = next(v for v in await invites.listing(session) if v.id == code.id)
    assert view.used == 2
    assert view.left == 0
    assert {name for _, name in view.invitees} == {"Первый", "Второй"}


async def test_code_runs_out_after_its_activations(session):
    await beta_on(session)
    boss = await admin(session)
    code = await invites.create(session, boss.id, max_activations=1)

    first = await make_user(session, "Успел")
    late = await make_user(session, "Опоздал")
    await session.commit()

    await invites.redeem(session, first, code.code)
    with pytest.raises(InviteError, match="разобрали"):
        await invites.redeem(session, late, code.code)


async def test_unknown_code_is_rejected(session):
    await beta_on(session)
    user = await make_user(session, "Гость")
    await session.commit()

    with pytest.raises(InviteError, match="Такого кода нет"):
        await invites.redeem(session, user, "ZZZZZZ")
    assert user.access_granted_at is None


async def test_admins_are_not_locked_behind_the_gate(session):
    """Коды выдаёт админ — запирать его за кодом значит запереть и выдачу."""
    boss = await admin(session)
    boss.access_granted_at = None
    await session.commit()

    assert invites.has_access(boss, beta=True) is True


async def test_turning_beta_off_opens_the_club_and_tells_those_who_waited(session):
    await beta_on(session)
    boss = await admin(session)
    waiting = await make_user(session, "Ждал у двери")
    waiting.onboarded_at = sa.func.now()  # знакомство «показывали» — но до кода
    await session.commit()

    opened = await invites.set_beta(session, boss.id, enabled=False)

    assert opened == 1
    await session.refresh(waiting)
    assert waiting.access_granted_at is not None
    # Знакомство он не видел: за кодом до него не доходило, поэтому показать надо.
    assert waiting.onboarded_at is None

    queued = (
        await session.execute(
            sa.select(Notification.kind).where(Notification.user_id == waiting.id)
        )
    ).scalars().all()
    assert queued == ["beta_opened"]
    assert await invites.beta_enabled(session) is False


async def test_beta_off_does_not_congratulate_the_admins(session):
    """Админов пускают по роли, отметки о доступе у них нет — но они не ждали."""
    await beta_on(session)
    boss = await admin(session)
    boss.access_granted_at = None
    await session.commit()

    opened = await invites.set_beta(session, boss.id, enabled=False)

    assert opened == 0
    left = await session.scalar(
        sa.select(sa.func.count()).select_from(Notification).where(Notification.user_id == boss.id)
    )
    assert left == 0


async def test_beta_off_does_not_disturb_those_who_already_had_access(session):
    await beta_on(session)
    boss = await admin(session)
    settled = await make_user(session, "Уже внутри")
    settled.access_granted_at = sa.func.now()
    await session.commit()

    await invites.set_beta(session, boss.id, enabled=False)

    left = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Notification)
        .where(Notification.user_id == settled.id)
    )
    assert left == 0


async def test_access_cannot_be_taken_twice(session):
    await beta_on(session)
    boss = await admin(session)
    code = await invites.create(session, boss.id, max_activations=5)
    user = await make_user(session, "Дважды")
    await session.commit()

    await invites.redeem(session, user, code.code)
    with pytest.raises(InviteError, match="уже есть"):
        await invites.redeem(session, user, code.code)


# --- через HTTP -------------------------------------------------------------


async def test_api_is_closed_until_the_code_is_entered(client, session):
    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    boss_headers = {"Authorization": f"Bearer {boss['token']}"}
    created = await client.post(
        "/api/admin/invites", json={"max_activations": 1}, headers=boss_headers
    )
    assert created.status_code == 201
    code = created.json()[0]["code"]

    # Гейт включаем после входа админа: он сам за ним не запирается.
    await SettingsService(session).set_many({"beta_invite_required": True}, None)
    await session.commit()

    guest = await login(client, 777301, "Гость")
    assert guest["user"]["access"] is False
    headers = {"Authorization": f"Bearer {guest['token']}"}

    closed = await client.get("/api/films", headers=headers)
    assert closed.status_code == 403
    assert closed.json()["detail"] == invites.NEED_CODE

    wrong = await client.post("/api/invites/redeem", json={"code": "NOPE12"}, headers=headers)
    assert wrong.status_code == 409

    ok = await client.post("/api/invites/redeem", json={"code": code}, headers=headers)
    assert ok.status_code == 200
    assert (await client.get("/api/films", headers=headers)).status_code == 200


async def test_only_superadmin_switches_the_beta_off(client, session):
    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    plain = await login(client, 777302, "Участник")
    await session.execute(
        sa.update(User).where(User.tg_id == 777302).values(role=UserRole.ADMIN)
    )
    await session.commit()

    denied = await client.post(
        "/api/admin/beta",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {plain['token']}"},
    )
    assert denied.status_code == 403

    allowed = await client.post(
        "/api/admin/beta",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {boss['token']}"},
    )
    assert allowed.status_code == 200


async def test_people_tab_shows_who_came_by_which_code(client, session):
    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    boss_headers = {"Authorization": f"Bearer {boss['token']}"}
    code = (
        await client.post(
            "/api/admin/invites", json={"max_activations": 3, "note": "первый поток"},
            headers=boss_headers,
        )
    ).json()[0]["code"]

    await SettingsService(session).set_many({"beta_invite_required": True}, None)
    await session.commit()

    guest = await login(client, 777303, "Пришёл по коду")
    await client.post(
        "/api/invites/redeem",
        json={"code": code},
        headers={"Authorization": f"Bearer {guest['token']}"},
    )

    people = (await client.get("/api/admin/people", headers=boss_headers)).json()
    row = next(person for person in people if person["display_name"] == "Пришёл по коду")
    assert row["invite_code"] == code
    assert row["invited_by"] == "Главный"
    assert row["has_access"] is True


async def test_moderator_cannot_read_the_people_tab(client, session):
    await login(client, SUPERADMIN_TG_ID, "Главный")
    other = await login(client, 777304, "Модератор")
    await session.execute(
        sa.update(User).where(User.tg_id == 777304).values(role=UserRole.MODERATOR)
    )
    await session.commit()

    denied = await client.get(
        "/api/admin/people", headers={"Authorization": f"Bearer {other['token']}"}
    )
    assert denied.status_code == 403


async def test_batch_gives_several_codes_at_once(session):
    """Пять кодов по два человека — не то же самое, что один код на десятерых."""
    boss = await admin(session)

    codes = await invites.create_many(session, boss.id, count=5, max_activations=2, note="поток")

    assert len({code.code for code in codes}) == 5
    assert all(code.max_activations == 2 for code in codes)
    listed = await invites.listing(session)
    assert len(listed) == 5
    assert all(view.left == 2 and view.note == "поток" for view in listed)


async def test_batch_rejects_nonsense(session):
    boss = await admin(session)

    with pytest.raises(InviteError, match="хотя бы один"):
        await invites.create_many(session, boss.id, count=0, max_activations=1)
    with pytest.raises(InviteError, match="хотя бы одна"):
        await invites.create_many(session, boss.id, count=1, max_activations=0)


async def test_batch_is_created_in_one_request(client):
    boss = await login(client, SUPERADMIN_TG_ID, "Главный")

    created = await client.post(
        "/api/admin/invites",
        json={"count": 3, "max_activations": 4},
        headers={"Authorization": f"Bearer {boss['token']}"},
    )

    assert created.status_code == 201
    body = created.json()
    assert len(body) == 3
    assert {row["max_activations"] for row in body} == {4}
    assert len({row["code"] for row in body}) == 3


async def test_codes_are_unique(session):
    boss = await admin(session)
    made = {(await invites.create(session, boss.id, 1)).code for _ in range(20)}
    stored = (await session.execute(sa.select(InviteCode.code))).scalars().all()
    assert len(made) == 20
    assert len(set(stored)) == len(stored)

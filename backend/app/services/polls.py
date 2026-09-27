"""Короткие опросы кнопками под сообщением бота — реестр и итоги.

Нативный опрос Telegram здесь не годится: в личку каждому уходит своё
сообщение, и у каждого получился бы отдельный опрос со своим итогом —
сложить их нельзя. Поэтому варианты — кнопки, а каждое нажатие ложится
в журнал аудита (entity="poll", action=ключ опроса, payload.option).

Передумать можно: засчитывается последний ответ человека.
"""

from dataclasses import dataclass, field
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Notification, User

ENTITY = "poll"


@dataclass(frozen=True, slots=True)
class Poll:
    question: str
    # Полные формулировки — в тексте сообщения, на кнопках — короткие:
    # длинную подпись Telegram обрезает посреди слова.
    options: tuple[str, ...]
    buttons: tuple[str, ...]


POLLS: dict[str, Poll] = {
    "wolf-day": Poll(
        question=(
            "В связи с накладками в расписании кинозала мы стоим перед выбором, "
            "что было бы вам предпочтительнее?"
        ),
        options=(
            "Просмотр «Волка с Уолл-стрит» в четверг в кинотеатре",
            "Просмотр «Волка с Уолл-стрит» в пятницу (там посвят цуеты...) в одной "
            "из аудиторий (притащим пуфики, запустим на экранах)",
        ),
        buttons=("1️⃣ Четверг, кинотеатр", "2️⃣ Пятница, аудитория"),
    ),
}


def dedup_key(key: str, user_id: int) -> str:
    """Ключ рассылки опроса: по нему же считаем, кому он дошёл."""
    return f"{ENTITY}:{key}:{user_id}"


def poll_text(key: str) -> str:
    poll = POLLS[key]
    lines = [poll.question, ""]
    lines += [f"{number}. {option}" for number, option in enumerate(poll.options, 1)]
    lines += ["", "Ответьте кнопкой ниже — передумать можно, засчитается последний ответ."]
    return "\n".join(lines)


def record(user_id: int, key: str, option: int, tg_id: int | None = None) -> AuditLog:
    return AuditLog(
        actor_id=user_id, entity=ENTITY, action=key, payload={"option": option, "tg_id": tg_id}
    )


def _latest(key: str):
    """Последний ответ каждого человека в опросе."""
    return (
        sa.select(
            AuditLog.actor_id,
            AuditLog.payload["option"].as_integer().label("option"),
            AuditLog.created_at,
            sa.func.row_number()
            .over(partition_by=AuditLog.actor_id, order_by=AuditLog.id.desc())
            .label("rank"),
        )
        .where(AuditLog.entity == ENTITY, AuditLog.action == key)
        .subquery()
    )


async def results(session: AsyncSession, key: str) -> list[int]:
    """Сколько человек выбрали каждый вариант — по последнему ответу каждого."""
    latest = _latest(key)
    counts = dict(
        (
            await session.execute(
                sa.select(latest.c.option, sa.func.count())
                .where(latest.c.rank == 1)
                .group_by(latest.c.option)
            )
        ).all()
    )
    return [counts.get(index, 0) for index in range(len(POLLS[key].options))]


@dataclass(slots=True)
class Voter:
    user_id: int
    display_name: str
    tg_username: str | None
    answered_at: datetime


@dataclass(slots=True)
class OptionResult:
    label: str
    votes: int = 0
    voters: list[Voter] = field(default_factory=list)


@dataclass(slots=True)
class PollResult:
    key: str
    question: str
    options: list[OptionResult]
    # Кому сообщение дошло и сколько из них ответили: «12 за четверг» без
    # «из 56» ничего не говорит о том, насколько это решение клуба.
    delivered: int
    answered: int
    sent_at: datetime | None


async def summary(session: AsyncSession) -> list[PollResult]:
    """Итоги всех опросов, которые уже рассылали, — свежие сверху.

    Поимённо: клуб маленький, и админу важно не только «сколько», но и
    «кто» — например, чтобы позвать в пятницу именно тех, кто за неё.
    """
    out: list[PollResult] = []
    for key, poll in POLLS.items():
        delivered, first_sent = (
            await session.execute(
                sa.select(sa.func.count(Notification.id), sa.func.min(Notification.sent_at)).where(
                    Notification.dedup_key.like(f"{ENTITY}:{key}:%"),
                    Notification.sent_at.is_not(None),
                )
            )
        ).one()
        latest = _latest(key)
        rows = (
            await session.execute(
                sa.select(latest.c.option, latest.c.created_at, User)
                .join(User, User.id == latest.c.actor_id)
                .where(latest.c.rank == 1)
                .order_by(latest.c.created_at)
            )
        ).all()
        if not delivered and not rows:
            continue

        options = [OptionResult(label=label) for label in poll.options]
        for option, answered_at, user in rows:
            if option is None or not 0 <= option < len(options):
                continue
            options[option].votes += 1
            options[option].voters.append(
                Voter(user.id, user.display_name, user.tg_username, answered_at)
            )
        out.append(
            PollResult(
                key=key,
                question=poll.question,
                options=options,
                delivered=delivered,
                answered=sum(item.votes for item in options),
                sent_at=first_sent,
            )
        )
    out.sort(key=lambda item: item.sent_at or datetime.min.astimezone(), reverse=True)
    return out

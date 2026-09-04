import logging
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_config
from app.core.auth import CurrentUser, issue_token
from app.core.telegram_auth import BotNotConfigured, InitDataError, parse_init_data
from app.db import get_session
from app.models import User
from app.models.enums import UserRole
from app.schemas import AuthOut, TelegramAuthIn, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthOut)
async def login_via_telegram(
    body: TelegramAuthIn, session: Annotated[AsyncSession, Depends(get_session)]
) -> AuthOut:
    config = get_config()
    try:
        tg_user = parse_init_data(body.init_data, config.telegram_bot_token)
    except BotNotConfigured as exc:
        # Причину пишем в лог, наружу отдаём нейтральное: имена переменных
        # окружения — не дело пользователя.
        logger.error("Вход невозможен: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Сервис временно недоступен, попробуйте позже.",
        ) from exc
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = (
        await session.execute(sa.select(User).where(User.tg_id == tg_user.tg_id))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            tg_id=tg_user.tg_id,
            tg_username=tg_user.username,
            display_name=tg_user.display_name,
            photo_url=tg_user.photo_url,
            tz=config.display_timezone,
            # Первый суперадмин назначается из окружения: иначе некому выдать
            # роли остальным (§9).
            role=(
                UserRole.SUPERADMIN
                if config.bootstrap_superadmin_tg_id == tg_user.tg_id
                else UserRole.USER
            ),
        )
        session.add(user)
    else:
        user.tg_username = tg_user.username
        user.display_name = tg_user.display_name
        user.photo_url = tg_user.photo_url

    await session.commit()
    await session.refresh(user)
    return AuthOut(
        token=issue_token(user.id), user=UserOut.model_validate(user, from_attributes=True)
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)

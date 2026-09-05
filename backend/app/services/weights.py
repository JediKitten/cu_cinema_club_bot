"""Расчёт весов (§4 спека).

Вес нигде не хранится вычисленным: в БД лежат сырые события, вес считается при
чтении по текущим коэффициентам. Формула собрана как SQL-выражение, а не считается
в Python, по двум причинам: рейтинг по всему каталогу должен быть одним запросом,
и песочница параметров (§13) должна пересчитывать его на лету с произвольными
коэффициентами, не трогая сохранённые настройки.
"""

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ColumnElement

from app.models import Interest
from app.models.enums import InterestKind


@dataclass(frozen=True, slots=True)
class WeightParams:
    wishlist_base_weight: float
    wishlist_half_life_days: float
    wishlist_weight_floor: float
    soon_weight: float
    soon_ttl_days: int

    @classmethod
    def from_settings(cls, values: dict[str, Any], **overrides: Any) -> "WeightParams":
        """overrides — ползунки песочницы: значения, ещё не сохранённые в БД."""
        merged = {**values, **{k: v for k, v in overrides.items() if v is not None}}
        return cls(
            wishlist_base_weight=float(merged["wishlist_base_weight"]),
            wishlist_half_life_days=float(merged["wishlist_half_life_days"]),
            wishlist_weight_floor=float(merged["wishlist_weight_floor"]),
            soon_weight=float(merged["soon_weight"]),
            soon_ttl_days=int(merged["soon_ttl_days"]),
        )


def age_days_expr(created_at: ColumnElement, at: ColumnElement | None = None) -> ColumnElement:
    now = at if at is not None else sa.func.now()
    return sa.extract("epoch", now - created_at) / 86400.0


def interest_weight_expr(
    params: WeightParams, at: ColumnElement | None = None
) -> ColumnElement:
    """Вес одной отметки на момент `at` (по умолчанию — сейчас)."""
    age = age_days_expr(Interest.created_at, at)

    def decay(age_expr: ColumnElement) -> ColumnElement:
        return sa.func.greatest(
            sa.literal(params.wishlist_weight_floor),
            sa.literal(params.wishlist_base_weight)
            * sa.func.power(
                sa.literal(0.5), age_expr / sa.literal(params.wishlist_half_life_days)
            ),
        )

    ttl = sa.literal(float(params.soon_ttl_days))

    # «Ближайшее» держит свой вес весь срок, а потом не сгорает, а становится
    # «Желаемым»: вес падает до базового и дальше затухает. Возраст для затухания
    # отсчитывается от момента истечения, а не от постановки отметки, — иначе
    # свежепротухшая отметка сразу оказалась бы наполовину затухшей.
    # Строгое «<»: ровно в момент истечения отметка уже считается «Желаемым».
    # Иначе SQL и Python расходились бы на границе — формула держала бы вес 3,
    # а интерфейс уже показывал бы «Желаемое».
    soon = sa.case(
        (age < ttl, sa.literal(params.soon_weight)),
        else_=decay(age - ttl),
    )

    return sa.case(
        (Interest.kind == InterestKind.WISHLIST, decay(age)),
        (Interest.kind == InterestKind.SOON, soon),
        else_=sa.literal(0.0),
    )


def is_expired_soon_expr(params: WeightParams) -> ColumnElement:
    """Отметка «Ближайшее», у которой вышел срок.

    Такая отметка уже ведёт себя как «Желаемое», но пользователю мы предлагаем
    продлить её — поэтому интерфейсу нужно отличать её от обычного «Желаемого».
    """
    return sa.and_(
        Interest.kind == InterestKind.SOON,
        age_days_expr(Interest.created_at) >= sa.literal(float(params.soon_ttl_days)),
    )


def effective_kind(kind: InterestKind, age_days: float, params: WeightParams) -> InterestKind:
    """Та же логика для кода на Python: чем отметка является сейчас."""
    if kind == InterestKind.SOON and age_days >= params.soon_ttl_days:
        return InterestKind.WISHLIST
    return kind


def active_interest_clause(at: ColumnElement | None = None) -> ColumnElement:
    """Отметка активна, если не снята. При расчёте «на момент времени» учитываем
    и то, что она к этому моменту уже была поставлена."""
    clause = Interest.revoked_at.is_(None)
    if at is not None:
        # Историческая реконструкция: снята позже интересующего момента — значит,
        # тогда была активна.
        clause = sa.and_(
            Interest.created_at <= at,
            sa.or_(Interest.revoked_at.is_(None), Interest.revoked_at > at),
        )
    return clause


def film_weight_expr(params: WeightParams, at: ColumnElement | None = None) -> ColumnElement:
    """Агрегат для GROUP BY films.id."""
    return sa.func.coalesce(sa.func.sum(interest_weight_expr(params, at)), 0.0)

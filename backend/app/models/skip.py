import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class FilmSkip(Base, CreatedAtMixin):
    """«Не интересно» из ленты (расширение по просьбе клуба).

    Не отметка и веса не несёт — только память о том, что фильм уже показывали
    и человек его пролистнул. Без неё лента крутила бы по кругу одно и то же.

    Отдельно от `interests` намеренно: там живут желания, и складывать в ту же
    таблицу отказы значило бы заводить «отрицательный интерес», которого нет
    ни в спеке, ни в формуле веса.
    """

    __tablename__ = "film_skips"
    __table_args__ = (sa.UniqueConstraint("user_id", "film_id", name="uq_film_skip"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    film_id: Mapped[int] = mapped_column(sa.ForeignKey("films.id"), index=True)

"""Сопоставление фильмов из разных источников.

Каталог наполнялся из Кинопоиска, поэтому у большинства фильмов пуст `tmdb_id`.
Отсеивать дубли в поиске только по нему нельзя: тот же фильм, найденный в TMDB,
покажется вторым — что и происходило.
"""

import re
import unicodedata

# Артикли и прочий шум, из-за которого «The Godfather» и «Godfather» считались
# бы разными фильмами.
NOISE = {"the", "a", "an"}


def normalize(title: str | None) -> str:
    """Приводит название к виду, пригодному для сравнения.

    Регистр, пунктуация, ё/е и артикли различаются между источниками, а фильм
    при этом один и тот же.
    """
    if not title:
        return ""
    # NFKD раскладывает «ё» на «е» с диакритикой, а «é» — на «e» с ней же.
    # Выбрасывая комбинирующие знаки, приводим и кириллицу, и латиницу разом.
    decomposed = unicodedata.normalize("NFKD", title.casefold())
    text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    words = [word for word in text.split() if word not in NOISE]
    return " ".join(words)


def keys(title_ru: str | None, title_orig: str | None, year: int | None) -> set[tuple[str, int]]:
    """Ключи, по которым фильм узнаётся.

    Год обязателен: у популярных названий есть ремейки, и без него «Дюна» 1984
    склеилась бы с «Дюной» 2021.
    """
    if year is None:
        return set()
    return {(normalize(t), year) for t in (title_ru, title_orig) if normalize(t)}


def is_same(
    left: tuple[str | None, str | None, int | None],
    right: tuple[str | None, str | None, int | None],
) -> bool:
    """Один ли это фильм: совпало хотя бы одно название при том же годе."""
    return bool(keys(*left) & keys(*right))

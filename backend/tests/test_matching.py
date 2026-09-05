"""Сопоставление фильмов из разных источников."""

from app.services.matching import is_same, keys, normalize


def test_normalize_ignores_case_and_punctuation():
    assert normalize("Кин-дза-дза!") == normalize("кин дза дза")
    assert normalize("Wall·E") == normalize("wall e")


def test_normalize_treats_yo_as_ye():
    """Источники пишут «ё» по-разному, фильм при этом один."""
    assert normalize("Ёлки") == normalize("Елки")


def test_normalize_drops_articles():
    assert normalize("The Godfather") == normalize("Godfather")


def test_same_film_matches_by_russian_title():
    kinopoisk = ("Бойцовский клуб", "Fight Club", 1999)
    tmdb = ("Бойцовский клуб", "Fight Club", 1999)
    assert is_same(kinopoisk, tmdb)


def test_same_film_matches_by_original_title_only():
    """Русские названия у источников расходятся чаще оригинальных."""
    kinopoisk = ("Первому игроку приготовиться", "Ready Player One", 2018)
    tmdb = ("Первому игроку приготовиться!", "Ready Player One", 2018)
    assert is_same(kinopoisk, tmdb)


def test_remakes_are_different_films():
    """Год обязателен: без него ремейк склеился бы с оригиналом."""
    assert not is_same(("Дюна", "Dune", 1984), ("Дюна", "Dune", 2021))


def test_without_year_nothing_matches():
    """Совпадение по одному названию слишком рискованно, чтобы прятать результат."""
    assert not is_same(("Дюна", "Dune", None), ("Дюна", "Dune", 2021))
    assert keys("Дюна", "Dune", None) == set()


def test_different_films_do_not_match():
    assert not is_same(("Солярис", "Solaris", 1972), ("Сталкер", "Stalker", 1979))


def test_normalize_handles_latin_diacritics():
    """Та же причина, что и с «ё»: источники пишут диакритику по-разному."""
    assert normalize("Amélie") == normalize("Amelie")

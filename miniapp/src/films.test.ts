import { describe, expect, it } from "vitest";
import { isSameFilm, replaceFilm } from "./films";
import type { FilmBrief } from "./types";

function film(over: Partial<FilmBrief>): FilmBrief {
  return {
    id: null,
    tmdb_id: null,
    title_ru: "Фильм",
    title_orig: null,
    year: null,
    poster_url: null,
    genres: [],
    directors: [],
    in_catalog: true,
    my_interests: [],
    ...over,
  };
}

describe("isSameFilm", () => {
  it("различает фильмы из Кинопоиска, у которых tmdb_id пуст у всех", () => {
    // Ровно та ошибка, из-за которой каталог превращался в копии одного фильма:
    // null === null делало совпадением любую пару.
    const bill = film({ id: 1, tmdb_id: null, title_ru: "Убить Билла" });
    const solaris = film({ id: 2, tmdb_id: null, title_ru: "Солярис" });
    expect(isSameFilm(bill, solaris)).toBe(false);
  });

  it("узнаёт один и тот же фильм по id", () => {
    expect(isSameFilm(film({ id: 7 }), film({ id: 7 }))).toBe(true);
  });

  it("узнаёт по tmdb_id, пока фильма ещё нет в каталоге", () => {
    expect(isSameFilm(film({ tmdb_id: 550 }), film({ tmdb_id: 550 }))).toBe(true);
  });

  it("не считает совпадением карточки без общего идентификатора", () => {
    expect(isSameFilm(film({ id: 1 }), film({ tmdb_id: 550 }))).toBe(false);
  });

  it("id важнее tmdb_id: один фильм мог попасть в каталог из разных источников", () => {
    expect(isSameFilm(film({ id: 1, tmdb_id: 550 }), film({ id: 2, tmdb_id: 550 }))).toBe(false);
  });
});

describe("replaceFilm", () => {
  it("меняет только совпавшую карточку", () => {
    const list = [
      film({ id: 1, title_ru: "Убить Билла" }),
      film({ id: 2, title_ru: "Солярис" }),
      film({ id: 3, title_ru: "Сталкер" }),
    ];
    const result = replaceFilm(
      list,
      film({ id: 2 }),
      (item) => item,
      (item) => ({ ...item, my_interests: ["wishlist" as const] }),
    );
    expect(result.map((f) => f.title_ru)).toEqual(["Убить Билла", "Солярис", "Сталкер"]);
    expect(result.map((f) => f.my_interests.length)).toEqual([0, 1, 0]);
  });

  it("оставляет список нетронутым, когда фильма в нём нет", () => {
    const list = [film({ id: 1 }), film({ id: 2 })];
    const result = replaceFilm(list, film({ id: 99 }), (i) => i, (i) => ({ ...i, year: 1900 }));
    expect(result).toEqual(list);
  });
});

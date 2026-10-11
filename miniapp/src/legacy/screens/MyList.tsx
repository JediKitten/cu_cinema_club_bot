import { myInterests, myWatched } from "../api";
import { PosterGrid } from "../components/PosterGrid";
import { Section } from "../components/Section";
import type { FilmBrief, InterestKind, InterestState } from "../types";
import { isSameFilm, replaceFilm } from "../films";
import { useFilmChanges } from "../filmChanges";
import { useLoad } from "../useLoad";

type Props = { onOpen(film: FilmBrief): void };

function daysLeft(expiresAt: string): number {
  return Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 86_400_000);
}

/** Сколько осталось у ближайшей к сгоранию отметки.
 *
 * В плитке подписи под каждым постером нет места, а знать, что срок поджимает,
 * нужно — поэтому одна строка на весь раздел вместо строки на фильм.
 */
function soonestHint(items: InterestState[]): string {
  const days = items
    .map((item) => (item.expires_at ? daysLeft(item.expires_at) : null))
    .filter((value): value is number => value !== null);
  if (days.length === 0) return "Эти отметки сгорают сами — продлить можно, когда придёт напоминание.";
  return `Сгорают сами: ближайшая — через ${Math.min(...days)} дн. Продлить можно, когда придёт напоминание.`;
}

/** Отмеченное: «Ближайшее» и «Желаемое».
 *
 * Отдельной страницей, а не разделом общего списка: в профиль ведут два числа,
 * и каждое должно открывать ровно то, что обещало.
 */
export function MyMarks({ onOpen }: Props) {
  const { data, setData: setItems, loading, error } = useLoad(myInterests, []);
  const items: InterestState[] = data ?? [];

  // Отметки меняют в карточке фильма, поэтому кнопок в плитке нет. Обработчик
  // остаётся: карточка возвращает обновлённый фильм, и список надо поправить.
  useFilmChanges((kinds, updated) => {
    setItems((current) =>
      replaceFilm(
        // Фильм без отметок в этом списке больше не место.
        (current ?? []).filter((item) => kinds.length > 0 || !isSameFilm(item.film, updated)),
        updated,
        (item) => item.film,
        // Сервер вернул фильм целиком — переносим и «Просмотрено», и признак
        // истёкшего срока, а не одни только отметки.
        (item) => ({ ...item, kinds, film: { ...item.film, ...updated, my_interests: kinds } }),
      ),
    );
  });

  const soon = items.filter((item) => item.kinds.includes("soon"));
  const wishlist = items.filter((item) => !item.kinds.includes("soon"));

  if (error) return <div className="screen"><div className="error">{error}</div></div>;
  if (loading && !data) return <div className="center">Загрузка…</div>;

  if (items.length === 0) {
    return (
      <div className="center">
        Пока ничего не отмечено.
        <br />
        Найдите фильм в каталоге и нажмите «Желаемое» или «Ближайшее».
      </div>
    );
  }

  return (
    <div className="screen">
      {soon.length > 0 && (
        <Section
          title="Ближайшее"
          count={soon.length}
          storageKey="mine-soon"
          hint={soonestHint(soon)}
        >
          <PosterGrid films={soon.map((item) => item.film)} onOpen={onOpen} />
        </Section>
      )}

      {wishlist.length > 0 && (
        <Section title="Желаемое" count={wishlist.length} storageKey="mine-wishlist">
          <PosterGrid films={wishlist.map((item) => item.film)} onOpen={onOpen} />
        </Section>
      )}
    </div>
  );
}

/** Просмотренное — тем же устройством, но своей страницей. */
export function MyWatched({ onOpen }: Props) {
  const { data, setData: setFilms, loading, error } = useLoad(myWatched, []);
  const films: FilmBrief[] = data ?? [];

  // «Смотрел» жмут той же кнопкой, что и отметки, — в карточке фильма.
  useFilmChanges((_kinds: InterestKind[], updated: FilmBrief) => {
    setFilms((current) => {
      const without = (current ?? []).filter((film) => !isSameFilm(film, updated));
      return updated.watched ? [updated, ...without] : without;
    });
  });

  if (error) return <div className="screen"><div className="error">{error}</div></div>;
  if (loading && !data) return <div className="center">Загрузка…</div>;

  if (films.length === 0) {
    return (
      <div className="center">
        Пока ничего не отмечено просмотренным.
        <br />
        Кнопка «Смотрел» есть в карточке фильма и в ленте.
      </div>
    );
  }

  return (
    <div className="screen">
      <Section
        title="Просмотренные"
        count={films.length}
        storageKey="mine-watched"
        hint="Отметка «Смотрел» ничему не мешает: фильм может быть и здесь, и в желаемом."
      >
        <PosterGrid films={films} onOpen={onOpen} />
      </Section>
    </div>
  );
}

import { useEffect, useState } from "react";
import { myInterests } from "../api";
import { FilmRow } from "../components/FilmRow";
import type { FilmBrief, InterestKind, InterestState } from "../types";

type Props = { onOpen(film: FilmBrief): void };

function daysLeft(expiresAt: string): number {
  return Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 86_400_000);
}

export function MyList({ onOpen }: Props) {
  const [items, setItems] = useState<InterestState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    myInterests()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Ошибка загрузки"))
      .finally(() => setLoading(false));
  }, []);

  function handleMarks(kinds: InterestKind[], updated: FilmBrief) {
    setItems((current) =>
      current
        // Фильм без отметок в этом списке больше не место.
        .filter((item) => item.film.id !== updated.id || kinds.length > 0)
        .map((item) =>
          item.film.id === updated.id
            ? { ...item, kinds, film: { ...item.film, my_interests: kinds } }
            : item,
        ),
    );
  }

  const soon = items.filter((item) => item.kinds.includes("soon"));
  const wishlist = items.filter((item) => !item.kinds.includes("soon"));

  if (loading) return <div className="center">Загрузка…</div>;
  if (error) return <div className="screen"><div className="error">{error}</div></div>;

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
        <>
          <h2 style={{ fontSize: 16, margin: 0 }}>Ближайшее</h2>
          <p className="hint" style={{ marginTop: -6 }}>
            Эти отметки сгорают сами — продлить можно, когда придёт напоминание.
          </p>
          {soon.map((item) => (
            <div key={item.film.id}>
              <FilmRow film={item.film} onOpen={onOpen} onMarksChange={handleMarks} />
              {item.expires_at && (
                <p className="hint" style={{ margin: "4px 0 0 12px" }}>
                  сгорит через {daysLeft(item.expires_at)} дн.
                </p>
              )}
            </div>
          ))}
        </>
      )}

      {wishlist.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, margin: "8px 0 0" }}>Желаемое</h2>
          {wishlist.map((item) => (
            <FilmRow
              key={item.film.id}
              film={item.film}
              onOpen={onOpen}
              onMarksChange={handleMarks}
            />
          ))}
        </>
      )}
    </div>
  );
}

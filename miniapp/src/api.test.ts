import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, OFFLINE_MESSAGE, searchFilms } from "./api";

/** Единственная дверь наружу у всего приложения — и до сих пор непокрытая.
 *
 * Проверяем не запросы, а то, что видит человек: сообщение об ошибке. Оно
 * приходит из трёх разных мест (detail от FastAPI, статус, обрыв сети),
 * и все три попадают в интерфейс как есть.
 */
function answer(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("показывает detail от FastAPI, а не «500 Internal Server Error»", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer({ detail: "Показ отменён" }, 409)));

    await expect(searchFilms("матрица")).rejects.toMatchObject({
      status: 409,
      message: "Показ отменён",
    });
  });

  it("при теле не-json оставляет статус", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>502</html>", { status: 502 })),
    );

    await expect(searchFilms("матрица")).rejects.toBeInstanceOf(ApiError);
  });

  it("обрыв связи объясняет по-русски, а не «Failed to fetch»", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(searchFilms("матрица")).rejects.toMatchObject({
      status: 0,
      message: OFFLINE_MESSAGE,
    });
  });

  it("успешный ответ отдаёт разобранное тело", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer([{ title_ru: "Матрица" }])));

    await expect(searchFilms("матрица")).resolves.toEqual([{ title_ru: "Матрица" }]);
  });

  it("протухшую сессию переполучает сама и повторяет запрос", async () => {
    // Вебвью Telegram живёт неделями, а сессия — тридцать дней: рано или
    // поздно токен перестаёт работать посреди работы.
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(answer({ detail: "Аккаунт недоступен" }, 401))
      .mockResolvedValueOnce(answer({ token: "новый", user: { id: 1 } }))
      .mockResolvedValueOnce(answer([{ title_ru: "Матрица" }]));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", {
      ...globalThis.window,
      Telegram: { WebApp: { initData: "auth_date=1&hash=2" } },
    });

    await expect(searchFilms("матрица")).resolves.toEqual([{ title_ru: "Матрица" }]);
    expect(fetchMock.mock.calls[1][0]).toContain("/api/auth/telegram");
  });
});

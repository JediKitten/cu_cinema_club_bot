import { describe, expect, it } from "vitest";
import { markButtons } from "./marks";

describe("markButtons", () => {
  it("пока ничего не отмечено, предлагает обе кнопки", () => {
    expect(markButtons(null, false)).toEqual([
      { kind: "wishlist", active: false, renew: false },
      { kind: "soon", active: false, renew: false },
    ]);
  });

  it("после выбора оставляет только выбранное — второе состояние невозможно", () => {
    expect(markButtons("wishlist", false)).toEqual([
      { kind: "wishlist", active: true, renew: false },
    ]);
    expect(markButtons("soon", false)).toEqual([{ kind: "soon", active: true, renew: false }]);
  });

  it("по истечении срока показывает «Желаемое» и предлагает продлить", () => {
    // Бэкенд к этому моменту уже отдаёт effective_kind = wishlist.
    expect(markButtons("wishlist", true)).toEqual([
      { kind: "wishlist", active: true, renew: false },
      { kind: "soon", active: false, renew: true },
    ]);
  });

  it("кнопка продления не выглядит нажатой: она ставит отметку заново", () => {
    const soon = markButtons("wishlist", true).find((b) => b.kind === "soon");
    expect(soon?.active).toBe(false);
    expect(soon?.renew).toBe(true);
  });
});

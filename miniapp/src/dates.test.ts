import { describe, expect, it } from "vitest";
import { dayLabel, shiftWeek, timeLabel, weekLabel } from "./dates";

describe("weekLabel", () => {
  it("не повторяет месяц, когда неделя внутри одного месяца", () => {
    expect(weekLabel("2026-09-07")).toBe("7–13 сентября");
  });

  it("называет оба месяца, когда неделя их пересекает", () => {
    expect(weekLabel("2026-09-28")).toBe("28 сентября–4 октября");
  });
});

describe("dayLabel", () => {
  it("склоняет месяц и называет день недели", () => {
    // Полдень, чтобы результат не зависел от зоны устройства.
    expect(dayLabel("2026-09-07T12:00:00Z")).toBe("понедельник, 7 сентября");
  });
});

describe("timeLabel", () => {
  it("дополняет нулём", () => {
    const iso = new Date(2026, 8, 7, 9, 5).toISOString();
    expect(timeLabel(iso)).toBe("09:05");
  });
});

describe("shiftWeek", () => {
  it("двигает на неделю вперёд и назад", () => {
    expect(shiftWeek("2026-09-14", 1)).toBe("2026-09-21");
    expect(shiftWeek("2026-09-14", -1)).toBe("2026-09-07");
  });

  it("не сбивается на переходе через месяц", () => {
    expect(shiftWeek("2026-09-28", 1)).toBe("2026-10-05");
  });

  it("остаётся понедельником через переход на зимнее время", () => {
    // Считаем в UTC именно поэтому: локальная полночь в такие дни сдвигается.
    const shifted = shiftWeek("2026-10-19", 1);
    expect(shifted).toBe("2026-10-26");
    expect(new Date(`${shifted}T00:00:00Z`).getUTCDay()).toBe(1);
  });
});

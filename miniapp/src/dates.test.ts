import { describe, expect, it } from "vitest";
import { dayLabel, timeLabel, weekLabel } from "./dates";

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

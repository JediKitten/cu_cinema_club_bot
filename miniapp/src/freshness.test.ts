import { describe, expect, it } from "vitest";
import { isOutdated } from "./freshness";

describe("isOutdated", () => {
  it("видит, что сервер новее сборки", () => {
    expect(isOutdated("b2c3d4e", "a1b2c3d")).toBe(true);
  });

  it("молчит, когда сборка и сервер из одного коммита", () => {
    expect(isOutdated("a1b2c3d", "a1b2c3d")).toBe(false);
  });

  it("не трогает разработку и сервер без версии", () => {
    expect(isOutdated("a1b2c3d", "dev")).toBe(false);
    expect(isOutdated("dev", "a1b2c3d")).toBe(false);
    expect(isOutdated(undefined, "a1b2c3d")).toBe(false);
  });
});

import { afterEach, describe, expect, it } from "vitest";
import { getSessionSecret } from "./secret";

describe("getSessionSecret", () => {
  const original = process.env.WORKBENCH_SESSION_SECRET;
  afterEach(() => {
    if (original === undefined) delete process.env.WORKBENCH_SESSION_SECRET;
    else process.env.WORKBENCH_SESSION_SECRET = original;
  });

  it("returns the env var when set", () => {
    process.env.WORKBENCH_SESSION_SECRET = "from-env";
    expect(getSessionSecret()).toBe("from-env");
  });

  it("falls back to a non-empty dev secret when unset", () => {
    delete process.env.WORKBENCH_SESSION_SECRET;
    expect(getSessionSecret().length).toBeGreaterThan(0);
  });

  it("falls back when the env var is empty", () => {
    process.env.WORKBENCH_SESSION_SECRET = "";
    expect(getSessionSecret().length).toBeGreaterThan(0);
  });
});

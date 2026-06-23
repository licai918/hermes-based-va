import { describe, expect, it } from "vitest";
import { json, problem } from "./respond";

describe("json", () => {
  it("defaults to 200 with application/json and a parseable body", async () => {
    const res = json({ hello: "world" });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(await res.json()).toEqual({ hello: "world" });
  });

  it("honors a custom status and extra headers", async () => {
    const res = json(
      { ok: true },
      { status: 201, headers: { "x-test": "1" } },
    );
    expect(res.status).toBe(201);
    expect(res.headers.get("x-test")).toBe("1");
    expect(res.headers.get("content-type")).toContain("application/json");
  });
});

describe("problem", () => {
  it("sets the status and an {error} body, merging extra fields", async () => {
    const res = problem(403, "forbidden", { code: "ROLE" });
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "forbidden", code: "ROLE" });
  });

  it("works without extra fields", async () => {
    const res = problem(401, "missing session");
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: "missing session" });
  });
});

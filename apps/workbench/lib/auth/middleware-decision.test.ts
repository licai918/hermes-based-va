import { WORKBENCH_ROLES } from "@toee/shared";
import { decideAccess, REFRESH_THRESHOLD_MS } from "./middleware-decision";
import { SESSION_IDLE_MS, type WorkbenchSession } from "./session";

const NOW = 1_800_000_000_000;

function session(
  role: WorkbenchSession["role"],
  lastActivityAt = NOW,
): WorkbenchSession {
  return { accountId: "acc", username: "user", role, lastActivityAt };
}
const rep = (last?: number) => session(WORKBENCH_ROLES.rep, last);
const supervisor = (last?: number) => session(WORKBENCH_ROLES.supervisor, last);

describe("decideAccess — public routes", () => {
  it("allows the login page for an unauthenticated visitor", () => {
    expect(decideAccess("/login", null, NOW).action).toBe("allow");
  });

  it("redirects an already-authenticated user away from /login to /copilot", () => {
    const d = decideAccess("/login", rep(), NOW);
    expect(d.action).toBe("redirect");
    expect(d.location).toBe("/copilot");
  });

  it("always allows the public auth API endpoints", () => {
    expect(decideAccess("/api/auth/login", null, NOW).action).toBe("allow");
    expect(decideAccess("/api/auth/session", null, NOW).action).toBe("allow");
    expect(decideAccess("/api/auth/logout", null, NOW).action).toBe("allow");
  });

  it("allows the /healthz liveness probe without a session (Cloud Run, issue #33)", () => {
    // The platform probe carries no session cookie; middleware must not redirect
    // it to /login or the health check never reaches the 200 route handler.
    expect(decideAccess("/healthz", null, NOW).action).toBe("allow");
  });

  it("allows /healthz for an authenticated user without redirecting", () => {
    expect(decideAccess("/healthz", rep(), NOW).action).toBe("allow");
  });
});

describe("decideAccess — unauthenticated protected access", () => {
  it("redirects a protected page to /login", () => {
    const d = decideAccess("/copilot", null, NOW);
    expect(d.action).toBe("redirect");
    expect(d.location).toBe("/login");
  });

  it("returns 401 for a protected API route", () => {
    expect(decideAccess("/api/copilot/cases", null, NOW).action).toBe(
      "unauthorized",
    );
  });
});

describe("decideAccess — expired sessions", () => {
  const expiredAt = NOW - SESSION_IDLE_MS - 1;

  it("treats an expired page session as logged out and clears the cookie", () => {
    const d = decideAccess("/copilot", rep(expiredAt), NOW);
    expect(d.action).toBe("redirect");
    expect(d.location).toBe("/login");
    expect(d.clearCookie).toBe(true);
  });

  it("treats an expired API session as 401 and clears the cookie", () => {
    const d = decideAccess("/api/copilot/cases", rep(expiredAt), NOW);
    expect(d.action).toBe("unauthorized");
    expect(d.clearCookie).toBe(true);
  });
});

describe("decideAccess — role gating", () => {
  it("redirects a rep away from an admin page to /copilot", () => {
    const d = decideAccess("/admin/knowledge", rep(), NOW);
    expect(d.action).toBe("redirect");
    expect(d.location).toBe("/copilot");
  });

  it("403s a rep on an admin API route", () => {
    expect(decideAccess("/api/admin/accounts", rep(), NOW).action).toBe(
      "forbidden",
    );
  });

  it("redirects a rep away from supervisor-only audit pages", () => {
    const d = decideAccess("/copilot/audit/auto-handled", rep(), NOW);
    expect(d.action).toBe("redirect");
    expect(d.location).toBe("/copilot");
  });

  it("allows a supervisor on admin pages and APIs", () => {
    expect(decideAccess("/admin/knowledge", supervisor(), NOW).action).toBe(
      "allow",
    );
    expect(decideAccess("/api/admin/accounts", supervisor(), NOW).action).toBe(
      "allow",
    );
  });
});

describe("decideAccess — sliding refresh", () => {
  it("does not refresh the cookie on very recent activity", () => {
    const d = decideAccess("/copilot", rep(NOW - 1_000), NOW);
    expect(d.action).toBe("allow");
    expect(d.refreshCookie).toBe(false);
  });

  it("refreshes the cookie once activity is older than the threshold", () => {
    const stale = NOW - REFRESH_THRESHOLD_MS - 1;
    const d = decideAccess("/copilot", rep(stale), NOW);
    expect(d.action).toBe("allow");
    expect(d.refreshCookie).toBe(true);
  });
});

import { formatChannel, formatRelativeTime, formatStatus } from "./format";

describe("formatChannel / formatStatus", () => {
  it("maps channel codes to labels", () => {
    expect(formatChannel("sms")).toBe("SMS");
    expect(formatChannel("email")).toBe("Email");
    expect(formatChannel("voice")).toBe("Voice");
  });

  it("maps status codes to labels", () => {
    expect(formatStatus("open")).toBe("Open");
    expect(formatStatus("in_progress")).toBe("In progress");
    expect(formatStatus("resolved")).toBe("Resolved");
  });
});

describe("formatRelativeTime", () => {
  const now = 10 * 24 * 60 * 60 * 1000; // 10 days in ms epoch-ish

  it("says 'just now' under a minute", () => {
    expect(formatRelativeTime(now - 30_000, now)).toBe("just now");
  });

  it("renders minutes, hours, and days", () => {
    expect(formatRelativeTime(now - 5 * 60_000, now)).toBe("5m ago");
    expect(formatRelativeTime(now - 2 * 3_600_000, now)).toBe("2h ago");
    expect(formatRelativeTime(now - 3 * 86_400_000, now)).toBe("3d ago");
  });

  it("falls back to an ISO date beyond a week", () => {
    const at = Date.UTC(2026, 0, 15, 12, 0, 0);
    const later = at + 30 * 86_400_000;
    expect(formatRelativeTime(at, later)).toBe("2026-01-15");
  });
});

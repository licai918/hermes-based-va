"use client";

// Workbench login form (ADR-0084 landing, ADR-0017 local username+password).
// Posts to the /api/auth/login BFF, which sets the HttpOnly session cookie on
// success; the form then navigates to /copilot (injectable as onSuccess so the
// flow is unit-testable without a real jsdom navigation). Failures map the BFF
// status to an operator-facing message (ADR-0018 lockout/disabled states).
import { useState, type FormEvent } from "react";
import { ROUTES } from "@toee/shared";

const MESSAGE_BY_STATUS: Record<number, string> = {
  400: "Enter your username and password.",
  401: "Invalid username or password.",
  403: "This account is disabled. Contact an administrator.",
  423: "Account temporarily locked after too many failed attempts. Try again later.",
};
const GENERIC_ERROR = "Sign-in failed. Please try again.";

export function LoginForm({ onSuccess }: { onSuccess?: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (res.ok) {
        if (onSuccess) onSuccess();
        else window.location.assign(ROUTES.copilot);
        return;
      }
      setError(MESSAGE_BY_STATUS[res.status] ?? GENERIC_ERROR);
    } catch {
      setError(GENERIC_ERROR);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "grid", gap: "0.75rem" }}>
      <div style={{ display: "grid", gap: "0.25rem" }}>
        <label htmlFor="username">Username</label>
        <input
          id="username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
      </div>
      <div style={{ display: "grid", gap: "0.25rem" }}>
        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      {error ? (
        <p role="alert" style={{ color: "#8a1c1c", margin: 0 }}>
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={busy}>
        {busy ? "Signing in..." : "Sign in"}
      </button>
    </form>
  );
}

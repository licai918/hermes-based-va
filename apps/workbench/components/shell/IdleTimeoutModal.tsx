"use client";

// 8-hour inactivity timeout modal (ADR-0018/0090). When the idle window elapses
// the modal appears, a best-effort server logout fires, and the operator must
// re-authenticate. The timing math is a pure helper so it is unit-testable; the
// component only wires it to a timer + render.
import { useEffect, useState } from "react";
import { ROUTES } from "@toee/shared";
import { SESSION_IDLE_MS } from "@/lib/auth/session";

export function msUntilIdle(
  lastActivityAt: number,
  idleMs: number,
  now: number,
): number {
  return lastActivityAt + idleMs - now;
}

export function IdleTimeoutModal({
  lastActivityAt,
  idleMs = SESSION_IDLE_MS,
}: {
  lastActivityAt: number;
  idleMs?: number;
}) {
  const [expired, setExpired] = useState(
    () => msUntilIdle(lastActivityAt, idleMs, Date.now()) <= 0,
  );

  useEffect(() => {
    const remaining = msUntilIdle(lastActivityAt, idleMs, Date.now());
    if (remaining <= 0) {
      setExpired(true);
      return;
    }
    const timer = setTimeout(() => setExpired(true), remaining);
    return () => clearTimeout(timer);
  }, [lastActivityAt, idleMs]);

  useEffect(() => {
    if (!expired) return;
    if (typeof fetch === "function") {
      void fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    }
  }, [expired]);

  if (!expired) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Session expired"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: "1.5rem",
          maxWidth: 420,
          textAlign: "center",
        }}
      >
        <h2>Session expired</h2>
        <p>You were signed out after 8 hours of inactivity. Please sign in again.</p>
        <a href={ROUTES.login}>Sign in again</a>
      </div>
    </div>
  );
}

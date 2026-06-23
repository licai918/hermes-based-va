"use client";

// Shared plumbing for the read-only audit views (ADR-0085/0086): a tiny
// fetch-on-mount hook with a discriminated state, a 404 helper for friendly
// not-found states, and inline style constants matching components/shell/*.
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { ApiError } from "@/lib/api/http";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "ready"; data: T };

// Loads once per dependency change, ignoring late results after unmount so a
// supervisor navigating away mid-fetch never triggers a setState-after-unmount.
export function useAsync<T>(
  load: () => Promise<T>,
  deps: unknown[],
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    load().then(
      (data) => {
        if (active) setState({ status: "ready", data });
      },
      (error) => {
        if (active) setState({ status: "error", error });
      },
    );
    return () => {
      active = false;
    };
    // `load` is recreated each render; `deps` carries the real inputs (e.g. id).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export const pageStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "1rem",
};

export const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
};

export const thStyle: CSSProperties = {
  textAlign: "left",
  padding: "0.5rem",
  borderBottom: "2px solid #e2e2e2",
  fontSize: "0.75rem",
  textTransform: "uppercase",
  letterSpacing: "0.03em",
  color: "#555",
};

export const tdStyle: CSSProperties = {
  padding: "0.5rem",
  borderBottom: "1px solid #f0f0f0",
  fontSize: "0.9rem",
  verticalAlign: "top",
};

export const cardStyle: CSSProperties = {
  border: "1px solid #e2e2e2",
  borderRadius: 8,
  padding: "1rem",
};

export const mutedStyle: CSSProperties = { color: "#666", fontSize: "0.8rem" };

export const failureStyle: CSSProperties = { color: "#8a1c1c", fontWeight: 600 };

export const dlStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  columnGap: "1rem",
  rowGap: "0.25rem",
  margin: 0,
};

export const dtStyle: CSSProperties = { ...mutedStyle };

export const ddStyle: CSSProperties = { margin: 0 };

// A single styled paragraph for loading / error / empty / not-found states. An
// optional ARIA role makes loading a status and failures an alert.
export function Notice({
  role,
  style,
  children,
}: {
  role?: "status" | "alert";
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <p role={role} style={{ ...mutedStyle, padding: "0.5rem 0", ...style }}>
      {children}
    </p>
  );
}

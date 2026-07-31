"use client";

// The review-inbox badge (0.0.5 S15, FR-22 / US9). The daily workflow the slice
// exists for is "log in -> see the badge (N) -> clear it", so the count has to be
// visible from wherever the admin already is, not only on the inbox page.
//
// A separate component rather than a field on the nav item: NavItem is a pure,
// Edge-safe {label, href} the server shell also renders, and a count baked into
// a static list is a number that is wrong by the time anyone reads it.
//
// ponytail: one fetch of the merged queue per page load, for supervisors and
// admins only. There is no cheaper source -- the count IS the merged queue's
// size, across three stores. If this ever shows up in the admin page budget, the
// fix is a count-only dispatch, not a cached number that can lie.
import { useEffect, useState } from "react";
import { listInbox } from "@/lib/api/admin-client";

export function InboxBadge() {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    listInbox()
      .then((result) => {
        if (!cancelled) setCount(result.count);
      })
      // Silent: a nav badge must never turn a load failure into a broken page,
      // and the inbox itself reports the error properly when you open it.
      .catch(() => {
        if (!cancelled) setCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (count === null || count === 0) return null;
  return (
    <span
      data-testid="inbox-badge"
      aria-label={`${count} pending review ${count === 1 ? "item" : "items"}`}
      style={{ marginLeft: "0.25rem", fontVariantNumeric: "tabular-nums" }}
    >
      ({count})
    </span>
  );
}

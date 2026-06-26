// Shared presentational formatters for workbench tables/timelines. Pure and
// locale-independent so they render identically on server and client and stay
// deterministic in tests.
import type { CaseChannel, CaseStatus } from "./gateway/types";

const CHANNEL_LABELS: Record<CaseChannel, string> = {
  sms: "SMS",
  email: "Email",
  voice: "Voice",
};

const STATUS_LABELS: Record<CaseStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
};

export function formatChannel(channel: CaseChannel): string {
  return CHANNEL_LABELS[channel];
}

export function formatStatus(status: CaseStatus): string {
  return STATUS_LABELS[status];
}

// Compact relative time for queue/timeline rows. Beyond a week it falls back to a
// fixed YYYY-MM-DD (UTC) so output never depends on the runtime locale/timezone.
export function formatRelativeTime(at: number, now: number): string {
  const deltaMs = Math.max(0, now - at);
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days <= 7) return `${days}d ago`;
  return new Date(at).toISOString().slice(0, 10);
}

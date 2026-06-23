import type { ReactNode } from "react";

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

// Shared empty-state primitive used by the Copilot queue, audit lists, and the
// admin routes when there is nothing to show (ADR-0090).
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div role="status" data-testid="empty-state">
      <strong data-empty-title>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action}
    </div>
  );
}

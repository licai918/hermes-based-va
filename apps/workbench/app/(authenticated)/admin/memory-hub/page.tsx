import { MemoryHub } from "@/components/admin/MemoryHub";

// Thin server shell for the Memory Hub (0.0.5 S14, FR-21/US9), mirroring the
// sibling admin pages (metrics/memory-audit/lexicon). The client component
// fetches the aggregate on mount; middleware/withSession already gate /admin/*
// to the supervisor and admin roles (ADR-0093).
export default function AdminMemoryHubPage() {
  return (
    <section>
      <h1>Memory</h1>
      <p style={{ fontSize: "0.8125rem", opacity: 0.7 }}>
        The seven memory layers, their live counts, and the console that governs
        each. Mirrors the at-a-glance table of docs/architecture/memory-layers.md.
      </p>
      <MemoryHub />
    </section>
  );
}

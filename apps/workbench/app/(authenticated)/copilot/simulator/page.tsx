// Conversation Simulator route (FR-8, 0.0.3 S02/S03). Thin server component,
// same shape as /copilot/page.tsx: re-reads the verified session (defense in
// depth behind the edge middleware) and hands off to the client container. Role
// gating is route-derived (ADR-0093) via lib/auth/access.ts -- this path is
// neither an audit nor an admin path, so every signed-in copilot role may use
// it, same as /copilot itself.
import { redirect } from "next/navigation";
import { ROUTES } from "@toee/shared";
import { getServerSession } from "@/lib/auth/current-session";
import { Simulator } from "@/components/copilot/Simulator";

export default async function SimulatorPage() {
  const session = await getServerSession();
  if (!session) redirect(ROUTES.login);

  return <Simulator />;
}

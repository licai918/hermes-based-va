import { redirect } from "next/navigation";
import { ROUTES } from "@toee/shared";

// The site root has no content of its own. Authenticated users land on the
// Copilot dashboard (ADR-0084); the middleware bounces unauthenticated requests
// to the login page before this renders.
export default function HomePage() {
  redirect(ROUTES.copilot);
}

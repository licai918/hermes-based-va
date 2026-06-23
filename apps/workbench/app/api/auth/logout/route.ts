import { handleLogout } from "@/lib/bff/auth-handlers";

export const runtime = "nodejs";

export function POST(): Response {
  return handleLogout({ secure: process.env.NODE_ENV === "production" });
}

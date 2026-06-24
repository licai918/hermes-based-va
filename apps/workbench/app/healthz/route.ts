// Cloud Run liveness probe (ADR-0098, issue #33): a cheap, dependency-free 200
// the platform health check hits to gate traffic. Node runtime to match the
// other workbench route handlers (session/auth) and standalone server output.
export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return Response.json({ status: "ok" });
}

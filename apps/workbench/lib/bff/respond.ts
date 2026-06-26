// JSON response helpers for workbench BFF route handlers. Uses the Web `Response`
// global (available in Node route handlers and Edge).

export function json<T>(
  data: T,
  init?: { status?: number; headers?: HeadersInit },
): Response {
  const headers = new Headers(init?.headers);
  headers.set("content-type", "application/json");
  return new Response(JSON.stringify(data), {
    status: init?.status ?? 200,
    headers,
  });
}

export function problem(
  status: number,
  message: string,
  extra?: Record<string, unknown>,
): Response {
  return json({ error: message, ...extra }, { status });
}

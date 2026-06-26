// Browser-side fetch helpers for the workbench BFF. Both helpers parse JSON and
// raise a typed ApiError (status + server `error` message) on non-2xx so callers
// can surface it through the global error banner (ADR-0090). Same-origin BFF
// calls only — the HttpOnly session cookie rides along automatically.

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseBody(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

function errorMessage(body: unknown, status: number): string {
  if (
    body &&
    typeof body === "object" &&
    "error" in body &&
    typeof (body as { error: unknown }).error === "string"
  ) {
    return (body as { error: string }).error;
  }
  return `request failed (${status})`;
}

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { accept: "application/json" } });
  const body = await parseBody(res);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status));
  return body as T;
}

export async function sendJson<T>(
  method: string,
  url: string,
  payload?: unknown,
): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: { "content-type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await parseBody(res);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status));
  return body as T;
}

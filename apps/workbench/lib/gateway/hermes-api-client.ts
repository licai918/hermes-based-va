// Server-side HTTP client for the per-profile Hermes API (ADR-0141). The BFF
// reaches structured workbench resources by POSTing a `{ tool, action, params }`
// envelope to the deterministic `POST /v1/tools:dispatch` endpoint with a
// per-profile bearer token. Tool Gate denials and backend failures arrive as a
// governed `{ ok: false, error: { class, message } }` body (HTTP 200, ADR-0020);
// only transport/auth problems are non-2xx. This client surfaces both as a thrown
// HermesApiError so callers map them onto the ADR-0090 error banner. The client is
// pure transport; snake_case->WorkbenchCase mapping + validation live in the BFF
// (lib/gateway/hermes-map.ts), keyed off the raw dispatch data.

export class HermesApiError extends Error {
  readonly errorClass: string;
  readonly httpStatus?: number;

  constructor(errorClass: string, message: string, httpStatus?: number) {
    super(message);
    this.name = "HermesApiError";
    this.errorClass = errorClass;
    this.httpStatus = httpStatus;
  }
}

// Narrow fetch shape so a test can pass a plain `(url, init) => Promise<Response>`
// fake; the real global `fetch` (wider params) is assignable to it.
export type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

export interface HermesApiClientConfig {
  baseUrl: string;
  token: string;
  fetchImpl?: FetchLike;
}

type DispatchSuccess = { ok: true; data: unknown };
type DispatchFailure = { ok: false; error?: { class?: string; message?: string } };
type DispatchBody = DispatchSuccess | DispatchFailure;

const DISPATCH_PATH = "/v1/tools:dispatch";

export class HermesApiClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly fetchImpl: FetchLike;

  constructor(config: HermesApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.token = config.token;
    this.fetchImpl = config.fetchImpl ?? fetch;
  }

  async dispatch(
    tool: string,
    action: string,
    params: Record<string, unknown> = {},
  ): Promise<unknown> {
    const res = await this.fetchImpl(`${this.baseUrl}${DISPATCH_PATH}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.token}`,
      },
      body: JSON.stringify({ tool, action, params }),
    });

    if (!res.ok) {
      throw new HermesApiError(
        "transport_error",
        `tool dispatch failed: HTTP ${res.status}`,
        res.status,
      );
    }

    const body = (await res.json()) as DispatchBody;
    if (!body || body.ok !== true) {
      const error = (body as DispatchFailure)?.error;
      throw new HermesApiError(
        error?.class ?? "unexpected_error",
        error?.message ?? "tool dispatch returned a governed error",
      );
    }
    return body.data;
  }
}

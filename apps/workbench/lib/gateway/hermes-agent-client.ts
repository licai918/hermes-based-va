// Server-side HTTP client for the per-profile Hermes agent-turn API (ADR-0147).
// Sibling to HermesApiClient: where that POSTs a `{ tool, action, params }`
// envelope to the deterministic `POST /v1/tools:dispatch`, this POSTs a draft
// request to `POST /v1/agent:turn` — a *genuine* (LLM) agent turn that returns a
// reply draft. Same per-profile bearer + `actor_account_id` convention; the draft
// is the agent's final_response (Fork E1), never a send (the internal_copilot
// profile structurally cannot send, ADR-0035/0067). A governed turn failure
// arrives as `{ ok: false, error: { class, message } }` (HTTP 200, ADR-0020); only
// transport/auth problems are non-2xx. Both surface as a thrown HermesApiError so
// callers map them onto the ADR-0104 status via hermesErrorToProblem.
import { HermesApiError, type FetchLike } from "./hermes-api-client";

export type DraftChannel = "sms" | "email" | "internal_note";

// The governed envelope's `data` for a draft turn: the channel echo, the draft
// text, and provenance (model + the structurally-no-send profile that produced it).
export interface AgentDraft {
  channel: string;
  draft: string;
  provenance?: { model?: string; profile?: string };
}

export interface HermesAgentClientConfig {
  baseUrl: string;
  token: string;
  // The acting workbench account (ADR-0141 actor attribution), baked in at
  // construction so every turn carries the real employee id under the shared bearer.
  actorAccountId?: string;
  fetchImpl?: FetchLike;
}

type TurnSuccess = { ok: true; data: AgentDraft };
type TurnFailure = { ok: false; error?: { class?: string; message?: string } };
type TurnBody = TurnSuccess | TurnFailure;

const AGENT_TURN_PATH = "/v1/agent:turn";

export class HermesAgentClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly actorAccountId?: string;
  private readonly fetchImpl: FetchLike;

  constructor(config: HermesAgentClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.token = config.token;
    this.actorAccountId = config.actorAccountId;
    this.fetchImpl = config.fetchImpl ?? fetch;
  }

  // Generate a reply draft for a case over the agent-turn API. Returns the governed
  // `data` (channel, draft, provenance); throws HermesApiError on a transport or
  // governed failure. Optional fields are only sent when present so the body shape
  // stays minimal (and an unauthenticated/system caller omits actor attribution).
  async generateDraft(input: {
    channel: DraftChannel;
    caseId: string;
    prompt?: string;
  }): Promise<AgentDraft> {
    const payload: Record<string, unknown> = {
      channel: input.channel,
      case_id: input.caseId,
    };
    if (input.prompt) payload.prompt = input.prompt;
    if (this.actorAccountId) payload.actor_account_id = this.actorAccountId;

    const res = await this.fetchImpl(`${this.baseUrl}${AGENT_TURN_PATH}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.token}`,
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new HermesApiError(
        "transport_error",
        `agent turn failed: HTTP ${res.status}`,
        res.status,
      );
    }

    const body = (await res.json()) as TurnBody;
    if (!body || body.ok !== true) {
      const error = (body as TurnFailure)?.error;
      throw new HermesApiError(
        error?.class ?? "unexpected_error",
        error?.message ?? "agent turn returned a governed error",
      );
    }
    return body.data;
  }
}

// Server-side HTTP client for the per-profile Hermes agent-turn API (ADR-0147).
// Sibling to HermesApiClient: where that POSTs a `{ tool, action, params }`
// envelope to the deterministic `POST /v1/tools:dispatch`, this POSTs a turn
// request to `POST /v1/agent:turn` — a *genuine* (LLM) agent turn. Two modes ride
// the one route: `generateDraft` returns a per-channel reply draft (sms/email/
// internal_note); `chatReply` (Slice 4, #39) returns a conversational reply for
// /api/copilot/chat. Same per-profile bearer + `actor_account_id` convention; the
// text is the agent's final_response (Fork E1), never a send (the internal_copilot
// profile structurally cannot send, ADR-0035/0067). A governed turn failure
// arrives as `{ ok: false, error: { class, message } }` (HTTP 200, ADR-0020); only
// transport/auth problems are non-2xx. Both surface as a thrown HermesApiError so
// callers map them onto the ADR-0104 status via hermesErrorToProblem.
import { HermesApiError, type FetchLike } from "./hermes-api-client";
import type { MemoryPreferenceSlot } from "./types";

export type DraftChannel = "sms" | "email" | "internal_note";

// One structured Customer Memory proposal (0.0.3 S14, FR-15): the draft turn's
// toee_customer_memory.upsert_preference call is propose-only (S13/ADR-0150 -- it
// never persists), so this is the framework-derived surfacing of that inert call,
// not a write. `evidenceTurn` is the optional verbatim customer phrase the write
// carried as `evidence`; the wire field stays `evidence_turn` (Python's naming,
// carried through unmodified per FR-15's envelope). S15 renders these with
// Accept/Dismiss; nothing here dispatches a write.
export interface AgentMemoryProposal {
  slot: MemoryPreferenceSlot;
  value: string;
  evidence_turn?: string | null;
}

// The governed envelope's `data` for a draft turn: the per-channel draft payload
// (mirroring the in-process toee_copilot_draft tool output — sms/email carry
// `channel`, email adds `subject`, internal_note carries `kind`), the draft text,
// provenance (model + the structurally-no-send profile that produced it), and the
// optional S14 proposals (present only when the turn proposed a memory write; chat
// never carries this — it's a conversational reply, not a draft).
export interface AgentDraft {
  channel?: string;
  kind?: string;
  subject?: string;
  draft: string;
  provenance?: { model?: string; profile?: string };
  proposals?: AgentMemoryProposal[];
}

export interface HermesAgentClientConfig {
  baseUrl: string;
  token: string;
  // The acting workbench account (ADR-0141 actor attribution), baked in at
  // construction so every turn carries the real employee id under the shared bearer.
  actorAccountId?: string;
  fetchImpl?: FetchLike;
}

type TurnSuccess = { ok: true; data: unknown };
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
    return (await this.postTurn(payload)) as AgentDraft;
  }

  // Run a conversational chat turn for a case (ADR-0147 Slice 4, #39). The staff
  // member's `message` rides as the prompt; the endpoint frames it as `channel:
  // "chat"` (a conversational reply, not a draft → no audit) and returns the agent's
  // final_response under `data.reply`. Throws HermesApiError on a transport/governed
  // failure, like generateDraft.
  async chatReply(input: { caseId: string; message: string }): Promise<string> {
    const data = (await this.postTurn({
      channel: "chat",
      case_id: input.caseId,
      prompt: input.message,
    })) as { reply?: unknown };
    return typeof data.reply === "string" ? data.reply : "";
  }

  // Shared transport for both turn modes: POST the bearer-authed envelope (with the
  // baked-in actor when configured), then unwrap the governed body — `data` on
  // success, a thrown HermesApiError on a non-2xx transport failure or an
  // `ok: false` governed failure (ADR-0020/0104).
  private async postTurn(
    payload: Record<string, unknown>,
  ): Promise<unknown> {
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

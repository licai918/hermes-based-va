import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleGetIntegrationsStatusViaApi,
  handleInitiateReconnectViaApi,
  handleReprobeNowViaApi,
  mapIntegrationsView,
} from "./integrations";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://admin.internal",
    token: "tok",
    actorAccountId: "seed-admin",
    fetchImpl,
  });
}

type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };

function dispatchResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
}

function rawEntry(overrides: Record<string, unknown> = {}) {
  return {
    key: "shopify",
    label: "Shopify (Composio)",
    kind: "composio_toolkit",
    configured: false,
    status: "not_configured",
    pinned_version: null,
    last_successful_call: null,
    last_probe: null,
    detail: "Not configured: set COMPOSIO_API_KEY in the deployment env.",
    ...overrides,
  };
}

function rawView(overrides: Record<string, unknown> = {}) {
  return {
    active_driver: "mock",
    integrations: [
      rawEntry(),
      rawEntry({
        key: "qbo",
        label: "QuickBooks (Composio)",
        configured: true,
        status: "configured",
        pinned_version: "20250101",
        detail: "Connected account present, pinned to 20250101.",
      }),
      rawEntry({ key: "square", label: "Square (Composio)" }),
      rawEntry({ key: "easyroutes", label: "EasyRoutes", kind: "easyroutes" }),
      rawEntry({ key: "simpletexting", label: "SimpleTexting", kind: "simpletexting" }),
      rawEntry({ key: "openrouter", label: "OpenRouter", kind: "openrouter" }),
      rawEntry({ key: "gadget", label: "Gadget mapping endpoint", kind: "gadget" }),
    ],
    ...overrides,
  };
}

describe("handleGetIntegrationsStatusViaApi", () => {
  it("dispatches get_integrations_status with no params over the admin profile", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(rawView());
    });

    const res = await handleGetIntegrationsStatusViaApi(client);
    expect(res.status).toBe(200);

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_integrations");
    expect(sent?.action).toBe("get_integrations_status");
    expect(sent?.params).toEqual({});
  });

  it("carries the active driver and every integration row", async () => {
    const client = apiClient(async () => dispatchResponse(rawView()));
    const res = await handleGetIntegrationsStatusViaApi(client);
    const body = (await res.json()) as ReturnType<typeof mapIntegrationsView>;

    expect(body.activeDriver).toBe("mock");
    expect(body.integrations.map((r) => r.key)).toEqual([
      "shopify",
      "qbo",
      "square",
      "easyroutes",
      "simpletexting",
      "openrouter",
      "gadget",
    ]);
  });

  it("preserves honest config/probe fields (never a fabricated healthy)", () => {
    const view = mapIntegrationsView(rawView());
    const shopify = view.integrations.find((r) => r.key === "shopify")!;
    expect(shopify.configured).toBe(false);
    expect(shopify.status).toBe("not_configured");
    // S15: nothing records last successful call; S16 fills last probe. Both null.
    expect(shopify.lastSuccessfulCall).toBeNull();
    expect(shopify.lastProbe).toBeNull();

    const qbo = view.integrations.find((r) => r.key === "qbo")!;
    expect(qbo.configured).toBe(true);
    expect(qbo.pinnedVersion).toBe("20250101");
  });

  it("maps a structured last_probe result through, and rejects a malformed one", () => {
    const view = mapIntegrationsView(
      rawView({
        integrations: [
          rawEntry({
            last_probe: {
              status: "failed",
              reason: "auth_expired: HTTP 401",
              checked_at: "2026-07-23T12:00:00+00:00",
            },
          }),
        ],
      }),
    );
    const probe = view.integrations[0]!.lastProbe!;
    expect(probe.status).toBe("failed");
    expect(probe.reason).toBe("auth_expired: HTTP 401");
    expect(probe.checkedAt).toBe("2026-07-23T12:00:00+00:00");

    // A present-but-malformed probe (missing checked_at) is a 502, not silently dropped.
    expect(() =>
      mapIntegrationsView(
        rawView({ integrations: [rawEntry({ last_probe: { status: "ok" } })] }),
      ),
    ).toThrow(/checked_at/);
  });

  it("does NOT default a missing `configured` to true (owner-blocked stays not-green)", () => {
    const bad = rawView({
      integrations: [rawEntry({ configured: undefined })],
    });
    expect(() => mapIntegrationsView(bad)).toThrow(/configured/);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleGetIntegrationsStatusViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
            { status: 200 },
          ),
      ),
    );
    expect(res.status).toBe(403);
  });

  it("rejects a malformed payload rather than passing it through", async () => {
    const client = apiClient(async () => dispatchResponse({ active_driver: 42 }));
    const res = await handleGetIntegrationsStatusViaApi(client);
    expect(res.status).toBe(502);
  });
});

describe("S17 reconnect (FR-25)", () => {
  it("rejects a non-Composio key before any dispatch (static tokens have no OAuth)", async () => {
    let called = false;
    const client = apiClient(async () => {
      called = true;
      return dispatchResponse({});
    });
    const res = await handleInitiateReconnectViaApi(
      client,
      "easyroutes",
      "https://wb/cb",
    );
    expect(res.status).not.toBe(200);
    expect(called).toBe(false);
  });

  it("returns the provider redirect URL on a successful link generation", async () => {
    const client = apiClient(async () =>
      dispatchResponse({
        integration_key: "shopify",
        redirect_url: "https://provider.example/oauth?x=1",
      }),
    );
    const res = await handleInitiateReconnectViaApi(client, "shopify", "https://wb/cb");
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      integrationKey: "shopify",
      redirectUrl: "https://provider.example/oauth?x=1",
    });
  });

  it("fails closed (502) when the backend returns no redirect URL, never a fake link", async () => {
    const client = apiClient(async () =>
      dispatchResponse({ integration_key: "shopify", redirect_url: null }),
    );
    const res = await handleInitiateReconnectViaApi(client, "shopify", "https://wb/cb");
    expect(res.status).toBe(502);
  });

  it("re-probe requires an integration key", async () => {
    const client = apiClient(async () => dispatchResponse({}));
    const res = await handleReprobeNowViaApi(client, "");
    expect(res.status).not.toBe(200);
  });

  it("re-probe maps the honest probe receipt", async () => {
    const client = apiClient(async () =>
      dispatchResponse({
        integration_key: "openrouter",
        status: "not_configured",
        reason: "not configured: OPENROUTER_API_KEY",
      }),
    );
    const res = await handleReprobeNowViaApi(client, "openrouter");
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      integrationKey: "openrouter",
      status: "not_configured",
      reason: "not configured: OPENROUTER_API_KEY",
    });
  });
});

"""v1 Domain Adapter Tool catalog (ADR-0059, ADR-0070).

One tool per integration with a fixed v1 ``action`` enum. The catalog lists every
valid action for each tool; per-profile allowlisting and Tool Gate enforcement
live in :mod:`toee_hermes.tool_gate` and the dispatch layer. Ported from the TS
``@toee/shared`` catalog so both runtimes share one source of truth.
"""

from __future__ import annotations

# Insertion order is preserved and mirrors the TS catalog.
TOOL_CATALOG: dict[str, tuple[str, ...]] = {
    "toee_identity_lookup": (
        "match_phone",
        "match_email_sender",
        "get_email_link_status",
        "link_identity",
    ),
    "toee_knowledge_search": ("search_public_site", "search_operational_policy"),
    "toee_shopify_read": (
        "get_order",
        "list_customer_orders",
        "search_products",
        "get_product",
    ),
    "toee_qbo_read": ("get_invoice", "list_customer_invoices", "get_ar_summary"),
    "toee_easyroutes_read": ("get_delivery_status", "get_route_details"),
    "toee_square_payment_link": ("send_payment_link",),
    "toee_sms_reply": ("send_message",),
    "toee_case": ("create_case", "update_case"),
    "toee_customer_memory": (
        "upsert_preference",
        "clear_preference",
        "get_preferences",
        # 0.0.3 S21 (FR-21): verified-only customer self-service "what do you
        # remember about me" read -- slot values only, no source/actor/
        # timestamps/binding_key (see the mock/datastore handlers). LLM-callable
        # on the EXTERNAL profile (NOT in _AGENT_EXCLUDED_ACTIONS, unlike
        # get_memory_audit below -- this one IS customer-facing by design).
        # It's also LLM-callable on internal_copilot for the same reason --
        # unexcluded actions ride this same shared toolset registration onto
        # every profile the toolset is attached to. Not a security gap: INTERNAL
        # already has get_preferences, a superset of this read.
        "get_my_memory_summary",
        # 0.0.3 S15 (FR-17): audit-only action for a dismissed S14 proposal --
        # persists no slot, only a Workbench Audit Log row (see the datastore
        # handler in hermes-runtime/hermes_runtime/datastore/handlers/memory.py).
        "dismiss_proposal",
        # 0.0.3 S20 (FR-20): Supervisor Memory Audit View read -- current slots +
        # full workbench_audit_log write history for a binding. Read-only; listed
        # in _AGENT_EXCLUDED_ACTIONS so it never reaches a live agent's tool loop,
        # only the admin BFF's deterministic tools:dispatch call.
        "get_memory_audit",
    ),
    "toee_case_manage": (
        "claim_case",
        "assign_case",
        "update_priority",
        "update_contact_reason",
        "resolve_case",
        "send_sms_message",
    ),
    "toee_copilot_draft": ("draft_sms", "draft_email", "draft_internal_note"),
    "toee_workbench_read": ("get_case", "list_cases", "get_audit_log", "get_thread", "get_thread_by_phone", "get_thread_by_email", "list_auto_handled", "get_auto_handled", "list_sales_outreach", "get_sales_outreach"),
    "toee_knowledge_ops": (
        "get_policy_slots",
        "update_policy_slot",
        "submit_for_eval",
        "rollback_published_policy",
        "get_corpus_status",
        # 0.0.4 S04 (FR-11): queues an `ingest` job for the background worker,
        # replacing 0.0.3 S11's display-only "run this CLI command" panel stub.
        # Admin-only (_AGENT_EXCLUDED_ACTIONS) -- it TRUNCATEs and reloads the
        # whole corpus, which is not a primitive any live turn may reach.
        "enqueue_corpus_reingest",
    ),
    "toee_eval_review": (
        "list_eval_runs",
        "get_eval_run",
        "sign_off_medium_failure",
        "promote_pending_policy",
    ),
    "toee_workbench_admin": (
        "list_accounts",
        "create_account",
        "update_account_role",
        "disable_account",
        "authenticate",
    ),
    # 0.0.3 S22 (FR-23, NFR-3): L6 Agent-experience store -- "what the agent
    # learns from doing the job" (distinct from L4 Customer Memory and L5's
    # authored corpus). The governed write is LLM-callable on internal_copilot
    # only (the S23 copilot review fork proposes); list_agent_experience is
    # admin-only (listed in _AGENT_EXCLUDED_ACTIONS, the get_memory_audit
    # precedent) -- reached only via the admin BFF's deterministic dispatch.
    # 0.0.3 S24 (FR-24): confirm_experience/reject_experience, the human
    # confirm gate -- also admin-only/_AGENT_EXCLUDED_ACTIONS, same reason.
    "toee_agent_experience": (
        "propose_experience",
        "list_agent_experience",
        "confirm_experience",
        "reject_experience",
    ),
    # 0.0.3 S26 (FR-28): aggregate-metrics admin panel. One read-only action
    # over existing tables + the new metric_event counters (memory injection,
    # knowledge found/miss). Admin-only (listed in _AGENT_EXCLUDED_ACTIONS, the
    # get_memory_audit precedent) -- reached only via the admin BFF's
    # deterministic tools:dispatch call, never a live agent's tool loop.
    "toee_metrics": ("get_aggregate_metrics",),
    # 0.0.3 S28 (FR-30): the Customer Memory retention sweep admin panel.
    # trigger_retention_sweep is a governed WRITE (ages out customer_memory_slot
    # rows per the ADR-0004/0116 class windows); get_retention_status is the
    # read-only last-run/per-class-counts view. Both admin-only (listed in
    # _AGENT_EXCLUDED_ACTIONS, the get_memory_audit precedent) -- reached only
    # via the admin BFF's deterministic tools:dispatch call or the schedulable
    # CLI entrypoint (hermes_runtime.retention_sweep), never a live agent's
    # tool-calling loop.
    # 0.0.4 S04 (FR-11) adds enqueue_retention_sweep: the admin button now queues
    # a `retention` job the background worker runs (which calls
    # trigger_retention_sweep, unchanged, with the actor from the payload).
    "toee_retention": (
        "trigger_retention_sweep",
        "enqueue_retention_sweep",
        "get_retention_status",
    ),
    # 0.0.4 S05 (FR-13): the dead-letter operator view + governed Replay.
    # list_dead_letters is the read (dead `job` rows plus the outbound_send
    # states S03/S04 leave that no dead-letter row captures); replay_job returns
    # ONE dead job to the queue, attributed to the acting supervisor and audited.
    # Both admin-only (listed in _AGENT_EXCLUDED_ACTIONS, the get_memory_audit
    # precedent) -- reached only via the admin BFF's deterministic tools:dispatch
    # call. Replay in particular re-runs arbitrary queued work, which is not a
    # primitive any live turn may reach.
    "toee_job_queue": ("list_dead_letters", "replay_job"),
    # 0.0.4 S15 (FR-23): the /admin/integrations status-page read. One read-only
    # action reporting, per integration (Composio Shopify/QBO/Square toolkits,
    # EasyRoutes, SimpleTexting, OpenRouter, and the Gadget mapping endpoint),
    # config presence + pinned version + last successful call + last probe result.
    # Admin-only (listed in _AGENT_EXCLUDED_ACTIONS, the get_memory_audit
    # precedent) -- reached only via the admin BFF's deterministic tools:dispatch
    # call on the supervisor_admin profile, never a live agent's tool loop. It
    # returns only status booleans + version pins, never a secret value (NFR-6).
    # 0.0.4 S17 (FR-25) adds the two in-app reconnect actions, both admin-only
    # (_AGENT_EXCLUDED_ACTIONS), reached only via the admin BFF's deterministic
    # tools:dispatch on supervisor_admin: initiate_reconnect generates a Composio
    # OAuth re-auth link (no token ever touches the workbench -- Composio holds the
    # credentials), and reprobe_now runs one on-demand health probe so a reconnected
    # integration's badge refreshes now rather than on the next scheduled cycle. Both
    # are governed WRITES, attributed to the acting admin and audited.
    "toee_integrations": (
        "get_integrations_status",
        "initiate_reconnect",
        "reprobe_now",
    ),
}


def tool_names() -> list[str]:
    """Return the v1 tool names in catalog order."""
    return list(TOOL_CATALOG)


def is_tool_name(value: str) -> bool:
    """True when ``value`` is a known v1 tool."""
    return value in TOOL_CATALOG


def is_tool_action(tool: str, action: str) -> bool:
    """True when ``action`` is valid for ``tool`` (and ``tool`` is known)."""
    actions = TOOL_CATALOG.get(tool)
    return actions is not None and action in actions

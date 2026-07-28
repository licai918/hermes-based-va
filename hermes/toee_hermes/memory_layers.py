"""Which memory layer each catalog action writes (FR-15, 0.0.5 S12).

``docs/architecture/memory-layers.md`` documents the L1-L7 layer map and its
boundary matrix in prose, and nothing enforced it: a new memory-writing action
could land without anyone deciding which layer owns it, and the prose would go
stale silently. This module is the machine-checked half -- a declarative table,
no runtime behavior. Its completeness is asserted by
``hermes-runtime/tests/test_memory_boundary_tripwires.py``.

**Every catalog action is declared, not just the writes.** ``TOOL_CATALOG`` is
action NAMES only -- it carries no read/write metadata -- so there is no honest
way to derive "the write actions" from it. A name-prefix heuristic
(``upsert_``/``clear_``/``propose_``/...) would silently mis-file
``dismiss_proposal`` (audit-only, no slot persisted) and silently miss any
future write whose name breaks the pattern: a fake safety net, which is the
exact failure this map exists to prevent. So the map covers the WHOLE catalog
and the completeness test is a pure set equality with no classification logic
anywhere. A non-write carries an explicit ``None``, which is a real declaration
("this action writes no memory-layer content"), not an escape hatch.

**The declaration rule.** The value is the memory layer whose CONTENT the action
creates, changes, or removes. Every governed action also appends a Workbench
Audit Log row; the audit trail is the record *of* a write, not the write itself,
so it never sets the value -- that is why ``dismiss_proposal``, which persists an
audit row and no slot, is ``None``. Reads are ``None`` even when they read a
layer, and so are the surfaces ``memory-layers.md`` puts explicitly OUTSIDE the
layer model (Workbench Accounts, the 6 governed operational-policy slots,
integration credentials, the job queue).

Python-only by design: this is a governance fixture, not a tool or an action, so
it carries no ``packages/shared`` mirror obligation -- NFR-9 catalog-sync covers
tools and actions, and this slice adds neither.
"""

from __future__ import annotations

from typing import Optional

# The documented layer model (docs/architecture/memory-layers.md "At a glance").
# 0.0.5 S01 landed the L7 semantic lexicon, so all seven layers are now declared
# by at least one action.
MEMORY_LAYERS: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5", "L6", "L7")

DECLARABLE_LAYERS: frozenset[Optional[str]] = frozenset({*MEMORY_LAYERS, None})

# Keys mirror toee_hermes.tool_catalog.TOOL_CATALOG exactly (asserted both ways
# by the completeness tripwire). A dict key holds exactly one value, so "exactly
# one layer per action" is structural here -- the tripwire's job is the set
# equality, not uniqueness.
LAYER_OF_ACTION: dict[tuple[str, str], Optional[str]] = {
    # --- L1 Identity Graph -------------------------------------------------
    # match_phone is NOT a pure lookup on the datastore (system-of-record)
    # backend: when no local identity_link row exists, `_match` falls through to
    # `_shopify_phone_fallback` (hermes-runtime/hermes_runtime/datastore/
    # handlers/identity.py), and a SINGLE Shopify phone match calls
    # `_upsert_identity_link`, persisting the identity_link row that
    # memory-layers.md counts as L1 ("Shopify/cross-system links, match
    # history"). Proven by hermes-runtime/tests/test_datastore_driver_identity
    # .py::test_match_phone_shopify_fallback_creates_identity_link. The mock
    # twin's match_phone is read-only; the declaration follows the backend that
    # actually persists.
    ("toee_identity_lookup", "match_phone"): "L1",
    # The other two really are reads. match_email_sender reaches the same
    # `_shopify_phone_fallback` but exits at its `channel != "sms"` guard before
    # any upsert; get_email_link_status is a bare SELECT.
    ("toee_identity_lookup", "match_email_sender"): None,
    ("toee_identity_lookup", "get_email_link_status"): None,
    # Upserts an identity_link row directly -- the one EXPLICIT L1 write.
    ("toee_identity_lookup", "link_identity"): "L1",
    # --- L5 Knowledge reads ------------------------------------------------
    ("toee_knowledge_search", "search_public_site"): None,
    # Reads the 6 governed operational-policy slots, which memory-layers.md
    # places OUTSIDE the layer model (and its boundary matrix pins as NOT L5).
    ("toee_knowledge_search", "search_operational_policy"): None,
    # --- live-facts tool reads (never memory, per the L5 boundary rows) -----
    ("toee_shopify_read", "get_order"): None,
    ("toee_shopify_read", "list_customer_orders"): None,
    ("toee_shopify_read", "search_products"): None,
    ("toee_shopify_read", "get_product"): None,
    ("toee_qbo_read", "get_invoice"): None,
    ("toee_qbo_read", "list_customer_invoices"): None,
    ("toee_qbo_read", "get_ar_summary"): None,
    ("toee_easyroutes_read", "get_delivery_status"): None,
    ("toee_easyroutes_read", "get_route_details"): None,
    ("toee_delivery_promise", "get_order_delivery"): None,
    ("toee_delivery_promise", "get_product_promise"): None,
    ("toee_delivery_promise", "get_delivery_quote"): None,
    # Sends an external payment link; persists no memory-layer content.
    ("toee_square_payment_link", "send_payment_link"): None,
    # --- L2 Conversation ---------------------------------------------------
    # The outbound turn joins the Customer Thread / SMS Session window.
    ("toee_sms_reply", "send_message"): "L2",
    # --- L3 Operational ----------------------------------------------------
    ("toee_case", "create_case"): "L3",
    ("toee_case", "update_case"): "L3",
    # --- L4 Customer Memory ------------------------------------------------
    ("toee_customer_memory", "upsert_preference"): "L4",
    ("toee_customer_memory", "clear_preference"): "L4",
    ("toee_customer_memory", "get_preferences"): None,
    ("toee_customer_memory", "get_my_memory_summary"): None,
    # 0.0.3 S15: a dismissed proposal persists NO slot -- only a Workbench Audit
    # Log row. Per the declaration rule above, an audit row is not the write.
    ("toee_customer_memory", "dismiss_proposal"): None,
    ("toee_customer_memory", "get_memory_audit"): None,
    # --- L3 Operational (case workflow) ------------------------------------
    ("toee_case_manage", "claim_case"): "L3",
    ("toee_case_manage", "assign_case"): "L3",
    ("toee_case_manage", "update_priority"): "L3",
    ("toee_case_manage", "update_contact_reason"): "L3",
    ("toee_case_manage", "resolve_case"): "L3",
    # The governed send appends the outbound turn to the thread, same as
    # toee_sms_reply.send_message -- an L2 write reached from the Workbench.
    ("toee_case_manage", "send_sms_message"): "L2",
    # --- drafts ------------------------------------------------------------
    # A draft is returned to the rep for review; nothing is persisted but the
    # `draft_generated` audit row.
    ("toee_copilot_draft", "draft_sms"): None,
    ("toee_copilot_draft", "draft_email"): None,
    ("toee_copilot_draft", "draft_internal_note"): None,
    # --- Workbench reads ---------------------------------------------------
    ("toee_workbench_read", "get_case"): None,
    ("toee_workbench_read", "list_cases"): None,
    ("toee_workbench_read", "get_audit_log"): None,
    ("toee_workbench_read", "get_thread"): None,
    ("toee_workbench_read", "get_thread_by_phone"): None,
    ("toee_workbench_read", "get_thread_by_email"): None,
    ("toee_workbench_read", "list_auto_handled"): None,
    ("toee_workbench_read", "get_auto_handled"): None,
    ("toee_workbench_read", "list_sales_outreach"): None,
    ("toee_workbench_read", "get_sales_outreach"): None,
    # --- knowledge ops -----------------------------------------------------
    ("toee_knowledge_ops", "get_policy_slots"): None,
    # The 6 governed operational-policy slots are authored content OUTSIDE the
    # layer model (memory-layers.md), and the boundary matrix pins them as NOT
    # the L5 corpus -- so these three writes declare no layer.
    ("toee_knowledge_ops", "update_policy_slot"): None,
    ("toee_knowledge_ops", "submit_for_eval"): None,
    ("toee_knowledge_ops", "rollback_published_policy"): None,
    ("toee_knowledge_ops", "get_corpus_status"): None,
    # Queues the ingest job that TRUNCATEs and reloads knowledge_chunk -- the
    # one catalog action that causes an L5 corpus write.
    ("toee_knowledge_ops", "enqueue_corpus_reingest"): "L5",
    # --- eval review -------------------------------------------------------
    ("toee_eval_review", "list_eval_runs"): None,
    ("toee_eval_review", "get_eval_run"): None,
    # Changes an eval record, which memory-layers.md lists under L3 Operational.
    ("toee_eval_review", "sign_off_medium_failure"): "L3",
    # Publishes a governed policy slot -- outside the layer model, as above.
    ("toee_eval_review", "promote_pending_policy"): None,
    # --- Workbench Accounts (outside the layer model) ----------------------
    ("toee_workbench_admin", "list_accounts"): None,
    ("toee_workbench_admin", "create_account"): None,
    ("toee_workbench_admin", "update_account_role"): None,
    ("toee_workbench_admin", "disable_account"): None,
    ("toee_workbench_admin", "authenticate"): None,
    # --- L6 Agent experience ----------------------------------------------
    ("toee_agent_experience", "propose_experience"): "L6",
    ("toee_agent_experience", "list_agent_experience"): None,
    # confirm/reject flip `status`, which is what makes an entry injectable (or
    # permanently not) -- an L6 content-state change, not bookkeeping.
    ("toee_agent_experience", "confirm_experience"): "L6",
    ("toee_agent_experience", "reject_experience"): "L6",
    # --- L7 Semantic Lexicon ------------------------------------------------
    # 0.0.5 S01 (FR-1/FR-3): the governed propose write inserts a
    # semantic_lexicon row -- L7 content, even though the row is inert until an
    # admin confirms it (same reasoning as propose_experience above: the
    # declaration follows the WRITE, not the injectability).
    ("toee_semantic_lexicon", "propose_lexicon_entry"): "L7",
    ("toee_semantic_lexicon", "list_lexicon_entries"): None,
    # 0.0.5 S02 (FR-3 decide side/FR-8): confirm/reject/retire flip `status`,
    # which is what makes an entry applicable (or permanently not) -- an L7
    # content-state change, exactly the confirm_experience reasoning above.
    ("toee_semantic_lexicon", "confirm_lexicon_entry"): "L7",
    ("toee_semantic_lexicon", "reject_lexicon_entry"): "L7",
    ("toee_semantic_lexicon", "retire_lexicon_entry"): "L7",
    # D7: an in-place UPDATE of the mapping on the SAME row -- the most direct
    # L7 content change there is.
    ("toee_semantic_lexicon", "edit_lexicon_entry"): "L7",
    # The admin's own entry, inserted already confirmed.
    ("toee_semantic_lexicon", "add_lexicon_entry"): "L7",
    # --- metrics -----------------------------------------------------------
    ("toee_metrics", "get_aggregate_metrics"): None,
    # --- L4 retention ------------------------------------------------------
    # The sweep ages out customer_memory_slot rows; the enqueue variant queues
    # the same sweep. Both remove L4 content.
    ("toee_retention", "trigger_retention_sweep"): "L4",
    ("toee_retention", "enqueue_retention_sweep"): "L4",
    ("toee_retention", "get_retention_status"): None,
    # --- job queue (outside the layer model) -------------------------------
    ("toee_job_queue", "list_dead_letters"): None,
    # Re-enqueues one dead job. Any memory write is the replayed job's own,
    # already declared on the action that queued it.
    ("toee_job_queue", "replay_job"): None,
    # --- integrations (credential/probe surface, outside the layer model) ---
    ("toee_integrations", "get_integrations_status"): None,
    ("toee_integrations", "initiate_reconnect"): None,
    ("toee_integrations", "reprobe_now"): None,
    # --- quality feedback (outside the layer model) -------------------------
    # ADR-0154's two stores (`interaction_review`, `draft_feedback`) hold
    # judgments ABOUT the system's output, never content the system reads back
    # into a turn. memory-layers.md enumerates L3 Operational as Follow-up Case
    # / Workbench Audit Log / auto-handled evidence / eval records -- these
    # tables are none of those, so the three writes declare no layer (see
    # hermes-runtime/hermes_runtime/datastore/handlers/feedback.py).
    # list_feedback is a bounded read over both tables.
    #
    # This USED to say "appear nowhere in the layer map", which made the
    # declaration rest on the map's silence rather than on a decision -- and a
    # reader would plausibly have expected these next to "eval records" under
    # L3. 0.0.5 S06 placed them explicitly: memory-layers.md's "Outside the
    # layer model, and why" section now carries a row for them, with the rule
    # that decides it. These four Nones are that row's other half. (Feedback
    # DERIVED into a proposal is a different thing and does become memory --
    # that is the `feedback_derived` provenance on an L6/L7 proposal, declared
    # on the propose action that writes it.)
    ("toee_feedback", "submit_interaction_review"): None,
    ("toee_feedback", "record_draft_outcome"): None,
    ("toee_feedback", "submit_draft_rating"): None,
    ("toee_feedback", "list_feedback"): None,
}

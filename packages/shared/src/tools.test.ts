import { describe, it, expect } from "vitest";
import {
  TOOL_CATALOG,
  TOOL_NAMES,
  isToolName,
  isToolAction,
} from "./tools";

describe("TOOL_CATALOG", () => {
  it("maps each v1 tool to its ADR-0070 action enum", () => {
    expect(TOOL_CATALOG.toee_identity_lookup).toEqual([
      "match_phone",
      "match_email_sender",
      "get_email_link_status",
    ]);
    expect(TOOL_CATALOG.toee_shopify_read).toEqual([
      "get_order",
      "list_customer_orders",
      "search_products",
      "get_product",
    ]);
    expect(TOOL_CATALOG.toee_customer_memory).toEqual([
      "upsert_preference",
      "clear_preference",
      "get_preferences",
    ]);
  });

  it("exposes get_thread on toee_workbench_read for Case Thread Context (ADR-0143)", () => {
    expect(TOOL_CATALOG.toee_workbench_read).toEqual([
      "get_case",
      "list_cases",
      "get_audit_log",
      "get_thread",
      "get_thread_by_phone",
      "list_auto_handled",
      "get_auto_handled",
      "list_sales_outreach",
      "get_sales_outreach",
    ]);
    expect(isToolAction("toee_workbench_read", "get_thread")).toBe(true);
    expect(isToolAction("toee_workbench_read", "get_thread_by_phone")).toBe(true);
    expect(isToolAction("toee_workbench_read", "list_auto_handled")).toBe(true);
  });

  it("exposes authenticate on toee_workbench_admin for the login cutover (ADR-0144)", () => {
    expect(TOOL_CATALOG.toee_workbench_admin).toEqual([
      "list_accounts",
      "create_account",
      "update_account_role",
      "disable_account",
      "authenticate",
    ]);
    expect(isToolAction("toee_workbench_admin", "authenticate")).toBe(true);
  });

  it("contains exactly the 18 v1 tool names", () => {
    expect([...TOOL_NAMES].sort()).toEqual(
      [
        "toee_agent_experience",
        "toee_semantic_lexicon",
        "toee_case",
        "toee_case_manage",
        "toee_copilot_draft",
        "toee_customer_memory",
        "toee_easyroutes_read",
        "toee_eval_review",
        "toee_feedback",
        "toee_identity_lookup",
        "toee_knowledge_ops",
        "toee_knowledge_search",
        "toee_qbo_read",
        "toee_shopify_read",
        "toee_square_payment_link",
        "toee_sms_reply",
        "toee_workbench_admin",
        "toee_workbench_read",
      ].sort(),
    );
  });

  it("exposes the toee_feedback tool shell actions (0.0.4 S02, ADR-0154)", () => {
    expect(TOOL_CATALOG.toee_feedback).toEqual([
      "submit_interaction_review",
      "record_draft_outcome",
      "submit_draft_rating",
      "list_feedback",
    ]);
    expect(isToolAction("toee_feedback", "submit_interaction_review")).toBe(true);
    expect(isToolAction("toee_feedback", "record_draft_outcome")).toBe(true);
    expect(isToolAction("toee_feedback", "submit_draft_rating")).toBe(true);
    expect(isToolAction("toee_feedback", "list_feedback")).toBe(true);
    // Schema test (S02 acceptance): a foreign action name is rejected.
    expect(isToolAction("toee_feedback", "delete_feedback")).toBe(false);
  });

  it("exposes the L6 Agent-experience store actions (0.0.3 S22/S24, FR-23/FR-24)", () => {
    expect(TOOL_CATALOG.toee_agent_experience).toEqual([
      "propose_experience",
      "list_agent_experience",
      "confirm_experience",
      "reject_experience",
    ]);
    expect(isToolAction("toee_agent_experience", "propose_experience")).toBe(true);
    expect(isToolAction("toee_agent_experience", "list_agent_experience")).toBe(true);
    expect(isToolAction("toee_agent_experience", "confirm_experience")).toBe(true);
    expect(isToolAction("toee_agent_experience", "reject_experience")).toBe(true);
  });

  it("exposes the L7 Semantic Lexicon store actions (0.0.5 S01/S02, FR-1/FR-3/FR-8)", () => {
    expect(TOOL_CATALOG.toee_semantic_lexicon).toEqual([
      "propose_lexicon_entry",
      "list_lexicon_entries",
      "confirm_lexicon_entry",
      "reject_lexicon_entry",
      "retire_lexicon_entry",
      "edit_lexicon_entry",
      "add_lexicon_entry",
    ]);
    expect(isToolAction("toee_semantic_lexicon", "propose_lexicon_entry")).toBe(
      true,
    );
    expect(isToolAction("toee_semantic_lexicon", "list_lexicon_entries")).toBe(
      true,
    );
    expect(isToolAction("toee_semantic_lexicon", "confirm_lexicon_entry")).toBe(
      true,
    );
    expect(isToolAction("toee_semantic_lexicon", "add_lexicon_entry")).toBe(true);
    // S02 EXTENDED the one read with filters instead of adding a second, and
    // retirement is a status -- there is no delete.
    expect(isToolAction("toee_semantic_lexicon", "list_lexicon_queue")).toBe(false);
    expect(isToolAction("toee_semantic_lexicon", "delete_lexicon_entry")).toBe(
      false,
    );
  });
});

describe("isToolName", () => {
  it("accepts a known tool name", () => {
    expect(isToolName("toee_case")).toBe(true);
  });

  it("rejects an unknown tool name", () => {
    expect(isToolName("toee_business_write")).toBe(false);
  });
});

describe("isToolAction", () => {
  it("accepts a valid action for the tool", () => {
    expect(isToolAction("toee_shopify_read", "get_order")).toBe(true);
  });

  it("rejects an action that belongs to a different tool", () => {
    expect(isToolAction("toee_shopify_read", "create_case")).toBe(false);
  });
});

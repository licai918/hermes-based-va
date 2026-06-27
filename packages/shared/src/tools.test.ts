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
      "list_auto_handled",
      "get_auto_handled",
      "list_sales_outreach",
      "get_sales_outreach",
    ]);
    expect(isToolAction("toee_workbench_read", "get_thread")).toBe(true);
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

  it("contains exactly the 15 v1 tool names", () => {
    expect([...TOOL_NAMES].sort()).toEqual(
      [
        "toee_case",
        "toee_case_manage",
        "toee_copilot_draft",
        "toee_customer_memory",
        "toee_easyroutes_read",
        "toee_eval_review",
        "toee_identity_lookup",
        "toee_knowledge_ops",
        "toee_knowledge_search",
        "toee_qbo_read",
        "toee_shopify_read",
        "toee_square_payment_link",
        "toee_textline_reply",
        "toee_workbench_admin",
        "toee_workbench_read",
      ].sort(),
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

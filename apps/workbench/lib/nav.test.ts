import { WORKBENCH_ROLES } from "@toee/shared";
import { navItemsForRole, roleLabel } from "./nav";

describe("navItemsForRole (ADR-0084)", () => {
  it("gives a rep the Copilot and Simulator entries", () => {
    const items = navItemsForRole(WORKBENCH_ROLES.rep);
    expect(items.map((i) => i.label)).toEqual(["Copilot", "Simulator"]);
    expect(items[0]?.href).toBe("/copilot");
    expect(items[1]?.href).toBe("/copilot/simulator");
  });

  it("gives a supervisor the simulator plus the governance entries, in order", () => {
    const items = navItemsForRole(WORKBENCH_ROLES.supervisor);
    expect(items.map((i) => i.label)).toEqual([
      "Copilot",
      "Simulator",
      // FR-21 (0.0.5 S14): the Memory hub is grill-locked ABOVE the consoles, so
      // it is the FIRST governance entry -- an entry point to the seven layers,
      // not a peer of the per-layer consoles that follow it.
      "Memory",
      // FR-22 (0.0.5 S15): the unified review inbox -- second, straight after the
      // hub and above the per-layer consoles it decides on behalf of.
      "Inbox",
      "Knowledge",
      "Eval",
      "Accounts",
      "Memory Audit",
      "Agent Experience",
      // FR-3/FR-8 (0.0.5 S02): the L7 Semantic Lexicon console.
      "Lexicon",
      "Metrics",
    ]);
    expect(items.find((i) => i.label === "Lexicon")?.href).toBe("/admin/lexicon");
    expect(items.find((i) => i.label === "Memory")?.href).toBe("/admin/memory-hub");
    expect(items.find((i) => i.label === "Inbox")?.href).toBe("/admin/inbox");
  });

  it("gives an admin the supervisor entries plus the admin-only Integrations page", () => {
    // 0.0.4 S15 (FR-23): Integrations is admin-only (a credential surface), so it
    // is appended for admin alone -- a supervisor must not see a link that 403s.
    const adminLabels = navItemsForRole(WORKBENCH_ROLES.admin).map((i) => i.label);
    const supervisorLabels = navItemsForRole(WORKBENCH_ROLES.supervisor).map(
      (i) => i.label,
    );
    expect(adminLabels).toEqual([...supervisorLabels, "Integrations"]);
    expect(
      navItemsForRole(WORKBENCH_ROLES.admin).find((i) => i.label === "Integrations")
        ?.href,
    ).toBe("/admin/integrations");
  });
});

describe("roleLabel", () => {
  it("maps each role id to its human-facing label", () => {
    expect(roleLabel(WORKBENCH_ROLES.rep)).toBe("Customer Service Rep");
    expect(roleLabel(WORKBENCH_ROLES.supervisor)).toBe("Workbench Supervisor");
    expect(roleLabel(WORKBENCH_ROLES.admin)).toBe("Workbench Admin");
  });
});

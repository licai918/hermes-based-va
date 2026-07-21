import { WORKBENCH_ROLES } from "@toee/shared";
import { navItemsForRole, roleLabel } from "./nav";

describe("navItemsForRole (ADR-0084)", () => {
  it("gives a rep the Copilot and Simulator entries", () => {
    const items = navItemsForRole(WORKBENCH_ROLES.rep);
    expect(items.map((i) => i.label)).toEqual(["Copilot", "Simulator"]);
    expect(items[0]?.href).toBe("/copilot");
    expect(items[1]?.href).toBe("/copilot/simulator");
  });

  it("gives a supervisor the simulator plus the six governance entries", () => {
    const labels = navItemsForRole(WORKBENCH_ROLES.supervisor).map(
      (i) => i.label,
    );
    expect(labels).toEqual([
      "Copilot",
      "Simulator",
      "Knowledge",
      "Eval",
      "Accounts",
      "Memory Audit",
      "Agent Experience",
      "Metrics",
    ]);
  });

  it("gives an admin the same six entries as a supervisor", () => {
    expect(navItemsForRole(WORKBENCH_ROLES.admin)).toEqual(
      navItemsForRole(WORKBENCH_ROLES.supervisor),
    );
  });
});

describe("roleLabel", () => {
  it("maps each role id to its human-facing label", () => {
    expect(roleLabel(WORKBENCH_ROLES.rep)).toBe("Customer Service Rep");
    expect(roleLabel(WORKBENCH_ROLES.supervisor)).toBe("Workbench Supervisor");
    expect(roleLabel(WORKBENCH_ROLES.admin)).toBe("Workbench Admin");
  });
});

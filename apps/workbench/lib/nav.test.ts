import { WORKBENCH_ROLES } from "@toee/shared";
import { navItemsForRole, roleLabel } from "./nav";

describe("navItemsForRole (ADR-0084)", () => {
  it("gives a rep only the Copilot entry", () => {
    const items = navItemsForRole(WORKBENCH_ROLES.rep);
    expect(items.map((i) => i.label)).toEqual(["Copilot"]);
    expect(items[0]?.href).toBe("/copilot");
  });

  it("gives a supervisor the four governance entries", () => {
    const labels = navItemsForRole(WORKBENCH_ROLES.supervisor).map(
      (i) => i.label,
    );
    expect(labels).toEqual(["Copilot", "Knowledge", "Eval", "Accounts"]);
  });

  it("gives an admin the same four entries as a supervisor", () => {
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

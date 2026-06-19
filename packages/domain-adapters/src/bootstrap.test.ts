import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { DOMAIN_ADAPTERS_PACKAGE } from "./index";

describe("monorepo bootstrap", () => {
  it("resolves the @toee/shared workspace package from a downstream package", () => {
    expect(HERMES_PROFILES.externalCustomerService).toBe(
      "customer_service_external",
    );
  });

  it("exposes the domain-adapters package marker", () => {
    expect(DOMAIN_ADAPTERS_PACKAGE).toBe("@toee/domain-adapters");
  });
});

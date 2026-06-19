// Integration backend for Domain Adapter Tools. Local dev and eval default to
// `mock`; `composio` and `rest` are wired per ADR-0132 and ADR-0137.
export type IntegrationDriver = "mock" | "composio" | "rest";

const KNOWN_DRIVERS: readonly IntegrationDriver[] = ["mock", "composio", "rest"];

// Resolves the configured integration driver, defaulting to `mock` when the
// environment value is unset or empty (ADR-0137). An unrecognized non-empty
// value is a configuration error and throws.
export function resolveIntegrationDriver(
  value: string | undefined = process.env.INTEGRATION_DRIVER,
): IntegrationDriver {
  if (value === undefined || value === "") {
    return "mock";
  }

  if ((KNOWN_DRIVERS as readonly string[]).includes(value)) {
    return value as IntegrationDriver;
  }

  throw new Error(
    `Unknown INTEGRATION_DRIVER "${value}". Expected one of: ${KNOWN_DRIVERS.join(", ")}.`,
  );
}

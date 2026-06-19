export const HERMES_PROFILES = {
  externalCustomerService: "customer_service_external",
  internalCopilot: "internal_copilot",
  supervisorAdmin: "supervisor_admin",
} as const;

export type HermesProfileId =
  (typeof HERMES_PROFILES)[keyof typeof HERMES_PROFILES];

export const WORKBENCH_ROLES = {
  rep: "customer_service_rep",
  supervisor: "workbench_supervisor",
  admin: "workbench_admin",
} as const;

export type WorkbenchRoleId =
  (typeof WORKBENCH_ROLES)[keyof typeof WORKBENCH_ROLES];

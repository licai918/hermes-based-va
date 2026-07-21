import type { ToolDriver } from "../execute-tool";
import { createMockDriver, type MockHandlerRegistry } from "./mock-driver";
import { identityMockHandlers } from "./identity";
import { caseMockHandlers } from "./case";
import { smsReplyMockHandlers } from "./sms-reply";
import { shopifyMockHandlers } from "./shopify";
import { qboMockHandlers } from "./qbo";
import { easyroutesMockHandlers } from "./easyroutes";
import { squareMockHandlers } from "./square";
import { knowledgeMockHandlers } from "./knowledge";
import { memoryMockHandlers } from "./memory";
import { adminStubMockHandlers } from "./admin-stubs";

export * from "./mock-driver";
export * from "./identity";
export * from "./case";
export * from "./sms-reply";
export * from "./shopify";
export * from "./qbo";
export * from "./easyroutes";
export * from "./square";
export * from "./knowledge";
export * from "./memory";
export * from "./admin-stubs";

// Default mock registry composed from every v1 Domain Adapter Tool. Tool
// ownership is disjoint per domain, so the fragments merge without key overlap.
// The eval fixture loader (later slice) rebuilds this with scenario-merged data
// via each domain's create*MockHandlers factory.
export const defaultMockRegistry: MockHandlerRegistry = {
  ...identityMockHandlers,
  ...caseMockHandlers,
  ...smsReplyMockHandlers,
  ...shopifyMockHandlers,
  ...qboMockHandlers,
  ...easyroutesMockHandlers,
  ...squareMockHandlers,
  ...knowledgeMockHandlers,
  ...memoryMockHandlers,
  ...adminStubMockHandlers,
};

export function createDefaultMockDriver(): ToolDriver {
  return createMockDriver(defaultMockRegistry);
}

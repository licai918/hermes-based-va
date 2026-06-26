// SDK-free Textline gateway pipeline primitives. The Fastify server, ingress
// phone match, and Hermes Core invocation land in issue #17 once the runtime
// shim is available; these pure primitives are stable regardless.
export * from "./pipeline/verify-textline";
export * from "./pipeline/normalize-inbound";
export * from "./pipeline/opt-out";
export * from "./pipeline/rate-limit";

export const HERMES_GATEWAY_PACKAGE = "@toee/hermes-gateway";

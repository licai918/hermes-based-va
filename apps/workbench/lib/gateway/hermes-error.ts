// Maps a governed tool error class onto the HTTP status the Workbench BFF returns
// for the ADR-0090 error banner. The tracer collapsed every per-profile API
// failure to a blanket 502; this aligns the surface with ADR-0104's retry/
// permanence intent and the ADR-0059/0136 ToolErrorClass vocabulary (plus the
// HermesApiClient's transport_error):
//
//   policy_blocked        -> 403  Tool Gate denial / write without an attributed actor
//   not_found             -> 404  governed read/write of a row that does not exist
//   conflict              -> 409  contended write (e.g. claim of an already-held case)
//   unknown_tool/action   -> 500  BFF<->profile contract bug, not the user's fault
//   vendor_timeout        -> 504  upstream integration timed out (retryable)
//   configuration_missing -> 503  a required integration is not wired yet
//   auth_expired          -> 502  upstream credential expired (bad gateway)
//   composio_api_error    -> 502  upstream integration error
//   unexpected_error      -> 502  unclassified governed failure
//   transport_error       -> 502  could not reach/parse the per-profile API
//
// Anything unrecognised defaults to 502 so a new error class still surfaces as a
// governed upstream failure rather than leaking as a 500.
import { problem } from "../bff/respond";
import { HermesApiError } from "./hermes-api-client";

const STATUS_BY_CLASS: Record<string, number> = {
  policy_blocked: 403,
  not_found: 404,
  conflict: 409,
  unknown_tool: 500,
  unknown_action: 500,
  vendor_timeout: 504,
  configuration_missing: 503,
  auth_expired: 502,
  composio_api_error: 502,
  unexpected_error: 502,
  transport_error: 502,
};

export function errorClassToStatus(errorClass: string): number {
  return STATUS_BY_CLASS[errorClass] ?? 502;
}

// Converts a thrown dispatch failure into a governed error Response. A
// HermesApiError carries the upstream error class and a governed (ADR-0020-safe)
// message; any other throw is treated as an unexpected upstream failure so the
// BFF never leaks an unmapped 500 to the error banner.
export function hermesErrorToProblem(err: unknown): Response {
  if (err instanceof HermesApiError) {
    return problem(errorClassToStatus(err.errorClass), err.message, {
      errorClass: err.errorClass,
    });
  }
  return problem(502, "service unavailable", { errorClass: "unexpected_error" });
}

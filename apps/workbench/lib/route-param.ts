// Next 16 App Router hands dynamic route params as the RAW, still
// percent-encoded path segment. Everything downstream wants the real id: the
// api clients encode once when building a BFF URL, and the audit review bar
// passes the value straight through as `subject_id`.
//
// Skipping this decode was invisible for as long as the only ids in play were
// fixtures like `pac_thread_a`, where encoding twice is a no-op. Real ids are
// not: an auto-handled record is keyed `customer_thread:sms:+14165550101`, so
// the detail fetch went out as `%253A` and 404'd ("Record not found"), and a
// review submitted from that page would have been filed under an id the list
// can never match.

/**
 * Decode one layer of percent-encoding from a Next dynamic route param.
 *
 * Falls back to the raw value when the segment is not valid encoding --
 * `decodeURIComponent` throws on a lone `%`, and a malformed URL should render
 * a "not found" page rather than a 500.
 */
export function decodeRouteParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

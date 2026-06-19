// SMS Opt-Out Keyword detection and the fixed STOP confirmation reply
// (ADR-0108, ADR-0015, ADR-0016). The gateway short-circuits the agent pipeline
// when an inbound body carries an opt-out keyword and sends exactly one brief
// English confirmation. Detection is whole-word and case-insensitive so a
// keyword embedded in another word (for example "nonstop") does not opt a
// customer out.
const OPT_OUT_KEYWORDS = ["STOP", "UNSUBSCRIBE", "ARRET"] as const;

const OPT_OUT_PATTERN = new RegExp(`\\b(?:${OPT_OUT_KEYWORDS.join("|")})\\b`, "i");

export function isOptOutKeyword(body: string): boolean {
  if (!body) {
    return false;
  }
  return OPT_OUT_PATTERN.test(body);
}

// Fixed brief confirmation sent once after opt-out (ADR-0016). No long
// explanations, repeated confirmations, or follow-up questions.
export const SMS_OPT_OUT_CONFIRMATION =
  "You have been unsubscribed from marketing messages. You can still text us for account support.";

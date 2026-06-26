"""SMS opt-out keyword detection and the fixed STOP confirmation reply.

(ADR-0108, ADR-0015, ADR-0016). The gateway short-circuits the agent pipeline
when an inbound body carries an opt-out keyword and sends exactly one brief
English confirmation. Detection is whole-word and case-insensitive so a keyword
embedded in another word (for example "nonstop") does not opt a customer out.
"""

from __future__ import annotations

import re

_OPT_OUT_KEYWORDS = ("STOP", "UNSUBSCRIBE", "ARRET")

_OPT_OUT_PATTERN = re.compile(
    r"\b(?:" + "|".join(_OPT_OUT_KEYWORDS) + r")\b", re.IGNORECASE
)


def is_opt_out_keyword(body: str) -> bool:
    if not body:
        return False
    return _OPT_OUT_PATTERN.search(body) is not None


# Fixed brief confirmation sent once after opt-out (ADR-0016). No long
# explanations, repeated confirmations, or follow-up questions.
SMS_OPT_OUT_CONFIRMATION = (
    "You have been unsubscribed from marketing messages. "
    "You can still text us for account support."
)

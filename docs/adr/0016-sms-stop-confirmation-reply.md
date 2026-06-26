# Brief STOP confirmation reply for SMS opt-out

When a customer sends an **SMS Opt-Out Keyword** (**STOP**, **UNSUBSCRIBE**, or **ARRET**), Hermes records **SMS Opt-Out** in the **Identity Graph** and sends one brief English confirmation reply, for example:

`You have been unsubscribed from marketing messages. You can still text us for account support.`

After opt-out, Hermes does not send marketing or proactive outbound texts to that number. If the customer later sends a new inbound support message, Hermes may still reply under **Always-On SMS Service** and governed service rules.

Hermes does not send long explanations, repeated confirmations, or follow-up questions after opt-out.

**Considered options:** silent opt-out with no reply (rejected—poor customer clarity); blocking all future inbound support SMS after STOP (rejected—over-broad interpretation of opt-out).

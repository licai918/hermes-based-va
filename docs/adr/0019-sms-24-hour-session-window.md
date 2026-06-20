# 24-hour Textline SMS session window with re-verification

Textline SMS conversations use a **24-hour session window** per phone number. Messages within the window continue the same Hermes session, preserving **Phone Match Verification** state, conversation context, and any in-progress **Follow-up Case** work.

If more than 24 hours pass without a new inbound message from that number, the session closes. The next inbound message starts a new session and the **Channel Gateway** runs **Ingress Phone Match** again before agent processing; Hermes does not assume the sender remains a **Verified Customer** from the prior session. See ADR-0043 for silent ingress-time verification behavior.

The **Copilot Workbench** may still display the full SMS thread history across sessions; only the agent runtime context is sliced by session window.

**Considered options:** indefinite SMS session continuity (rejected—stale verification and context risk); 1-hour window (rejected—too short for B2B customers who reply next day).

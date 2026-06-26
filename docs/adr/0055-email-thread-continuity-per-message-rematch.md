# Email thread continuity with per-message sender rematch

On the email channel, agent runtime context follows the long-lived **Email Thread** for an authenticated sender rather than a 24-hour session window like Textline SMS.

Each inbound email still runs **Sender Identity Intake** and **Email Sender Match** on the authenticated **From** address before agent processing, so verification is fresh at message receipt without a customer-facing verification ceremony. Hermes does not carry prior-thread **Verified Customer** authorization forward if a later inbound message fails sender match or changes to an unmatched or ambiguous state.

**Email Thread** continuity is for conversation context and case follow-up only. It does not bypass **Tool Gate**, **Contact Reason** rules, or non-customer playbooks.

**Considered options:** reuse the 24-hour **SMS Session** timeout for email (rejected—poor fit for B2B email reply cadence); verify only the first message in a thread and skip later rematch (rejected—stale or changed sender risk); use a fixed seven-day email session window (rejected—arbitrary cutoff without matching the natural thread model).

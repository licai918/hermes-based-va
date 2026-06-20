# toee_knowledge_search and toee_copilot_draft v1 actions

## toee_knowledge_search

`toee_knowledge_search` exposes two v1 actions:

| Action | Purpose |
|--------|---------|
| `search_public_site` | Search **Public Site Knowledge** rebuilt from **Shopify Knowledge Sync** and **Tavily Gap Crawl** |
| `search_operational_policy` | Search **Published Operational Policy** only |

**Tool Gate** rules:

- External and Copilot profiles may call both actions
- `search_operational_policy` returns only **Published Operational Policy** content, never **Pending Eval Knowledge** or empty-slot improvisation
- Empty **Required Operational Policy Slot** content yields a governed no-policy result for safe customer fallback

## toee_copilot_draft

`toee_copilot_draft` exposes three v1 actions on the **Internal Copilot Profile**:

| Action | Purpose |
|--------|---------|
| `draft_sms` | Draft a Textline SMS reply for employee review |
| `draft_email` | Draft an email reply for employee review |
| `draft_internal_note` | Draft an internal case note for employee review |

Draft actions never send to customers or write business systems in v1. Confirmed customer sends use governed write paths such as `toee_textline_reply` in later approved phases.

**Considered options:** one `search` action with layer parameter (rejected—weaker eval and gate clarity); one `create_draft` action with channel enum (rejected—three explicit draft types match Copilot workflows better); let external profile search pending operational policy (rejected—publish eval gate).

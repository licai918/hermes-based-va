# Copilot Workbench role access for phone MVP

The first-version **Copilot Workbench** is limited to employees who handle customer follow-up. Access is role-based; AR summaries and call transcripts are not open to all staff by default.

| Role | MVP access |
|------|------------|
| **Customer Service Rep** | View case list, call summary and transcript, draft SMS/email replies, mark cases resolved |
| **Supervisor** | All rep access plus adjust priority, complete **Knowledge Gap Prompt** slots, sign off medium-severity **Launch Eval Gate** failures |
| **Admin** | System configuration and user management; may overlap with Supervisor for knowledge publish in a small team |
| **Sales, warehouse, finance, and other roles** | No default access |

Principle: only employees who need to resolve **Follow-up Cases** may view case content. Field-level masking for sensitive accounting detail can be added later; MVP starts with role gate only.

**Considered options:** company-wide Copilot access (rejected—overexposes AR and call content); separate helpdesk product (rejected—cases stay in Hermes Copilot Workbench).

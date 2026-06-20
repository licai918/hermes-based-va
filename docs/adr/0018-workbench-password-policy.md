# Workbench account password policy for MVP

**Workbench Account** passwords in the first version follow a minimum security baseline:

- Minimum length: 12 characters
- Complexity: uppercase, lowercase, and digits (special characters not required)
- Login throttling: lock account for 15 minutes after 5 failed attempts
- Session timeout: automatic logout after 8 hours of inactivity

Mandatory 90-day password rotation and MFA are deferred to a later phase.

**Considered options:** shorter 8-character passwords (rejected—weak for accounts that can view AR and call content); MFA on day one (deferred—adds rollout friction for a small internal team).

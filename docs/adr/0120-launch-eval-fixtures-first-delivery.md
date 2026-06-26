# Launch eval YAML fixtures as the first delivery artifact

Launch eval suites are specified as versioned YAML fixtures before the **Launch Eval Runner** implementation is complete.

## text_first_launch

Repository fixtures for scenario ids **01–18** and **24–26** are the source of truth for SMS **Text-First Launch** wording, mock overrides, and assertions.

## email_go_live

Repository fixtures for scenario ids **14–18** and **19–23** under `eval/scenarios/email/` are the source of truth for email-channel go-live. See ADR-0126.

The runner must conform to these files rather than the files being generated from runner behavior.

**Considered options:** implement the runner before writing fixtures (rejected—delays review of launch-gate content); write only Customer Memory fixtures (rejected—incomplete SMS go-live gate); store scenarios outside the repo (rejected—weak version control with code and policy changes).

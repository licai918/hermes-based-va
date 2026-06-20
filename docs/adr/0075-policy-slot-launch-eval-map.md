# Policy slot to launch eval scenario map for publish eval

**Knowledge Publish Eval Gate** uses `eval/policy_slot_map.yaml` to determine which **Launch Eval Scenario** ids run when a **Required Operational Policy Slot** is submitted through `toee_knowledge_ops.submit_for_eval`.

Each slot maps to one or more scenario ids tied to that policy area. Every publish-eval run also includes the fixed regression subset `[2, 7, 8]`:

- 2 — unmatched caller zero disclosure
- 7 — prompt injection and overreach
- 8 — empty required operational policy slot behavior

The runner records the report with `suite: policy_publish` and links the changed slot id and pending knowledge version in the **Launch Eval Report**.

Full scenarios 1–18 remain required for initial Text-First go-live and for model, prompt, or tool-permission changes.

**Considered options:** run all launch scenarios on every policy edit (rejected—too slow); let supervisors manually pick scenario ids (rejected—not repeatable); omit regression subset on small edits (rejected—policy edits can still break hard boundaries).

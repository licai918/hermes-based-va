# Text-first launch on Textline before voice layer

The first external go-live uses **Text-First Launch** on Textline SMS, not phone. Hermes text core, identity rules, tool integrations, knowledge layers, Copilot Workbench, and the **Launch Eval Gate** are validated on SMS first so issues surface in a lower-latency, easier-to-debug channel.

After the text path is stable, the voice layer is added by connecting Net2phone transfer rules and Twilio ConversationRelay to the same Hermes text core. Voice does not introduce a separate business brain.

**Phase order:**

1. Textline SMS — external customer service MVP (go-live)
2. Voice — Net2phone → Twilio ConversationRelay on validated text core
3. Email, web chat, and outbound campaigns — later phases

Email and web chat are not part of first go-live. Copilot Workbench is built alongside text MVP to handle **Follow-up Cases** from SMS.

**Considered options:** phone-first go-live (rejected—operator preference to expose integration and policy issues on text first); parallel phone and SMS launch (rejected—doubles launch risk).

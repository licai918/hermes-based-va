# Single opening greeting for all Net2phone transfers

Hermes uses one **Opening Greeting** framework for every call that Net2phone transfers to the Twilio Hermes line. The greeting does not branch on Net2phone transfer trigger (after-hours versus no-answer).

**Personalized Opening Greeting** still varies only by caller identity context from Shopify phone match (verified, unmatched, ambiguous). Transfer-reason metadata from Net2phone may be stored for analytics and operations reporting, but it does not select a different welcome script.

**Considered options:** separate after-hours and no-answer greeting scripts (rejected—unnecessary complexity for MVP); dynamic greeting based on Hermes business-hours knowledge (rejected—routing and schedules are owned by Net2phone, not Hermes).

# Cloud Run hosting with services activated by Hermes core needs

**Hermes VA** uses **Hermes Core** as the shared text orchestration brain. Unlike the prior Gemini VA approach that treated the application stack as the core, this project anchors production hosting on Google Cloud Run and adds Google Cloud services only when **Hermes Core** capabilities require them.

Cloud Run is the default runtime for Hermes APIs, webhooks, and websocket endpoints. Database, queue, cache, scheduler, and secret services are provisioned incrementally based on verified Hermes requirements rather than pre-activating a fixed bundle such as PostgreSQL, Redis, or GKE for MVP.

Infrastructure decisions should be traceable to a concrete Hermes feature or ADR need. Services not required by the current Hermes profile and channel scope stay unprovisioned.

**Considered options:** pre-provisioning PostgreSQL + Redis + GKE for day one (rejected—over-provision before Hermes requirements are proven); non-GCP hosting (rejected—operator preference for Cloud Run).

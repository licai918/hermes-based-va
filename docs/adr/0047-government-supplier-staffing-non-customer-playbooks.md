# Government, supplier, and staffing non-customer playbooks with urgency uplift

After **Contact Reason** classification, Hermes applies these first-response playbooks for preset **Non-Customer Contact** types on the **External Customer Service Profile**.

**Government (`government`):** Hermes runs standard non-customer intake, creates a **Follow-up Case**, and marks it **Urgent Follow-up Case** by default because tax and regulatory contacts are time-sensitive.

**Supplier (`supplier`):** Hermes runs standard non-customer intake and creates a **Follow-up Case** at normal priority. If the caller mentions invoice reconciliation, accounts-payable follow-up, delivery exception, or shipment problem language, Hermes upgrades the case to **Urgent Follow-up Case**.

**Staffing (`staffing`):** Hermes runs standard non-customer intake and creates a **Follow-up Case** at normal priority. If the caller mentions payroll, wage dispute, workplace safety, or harassment language, Hermes upgrades the case to **Urgent Follow-up Case**.

All three playbooks preserve zero customer-account disclosure and do not use **Registered Phone** customer-recovery language.

**Considered options:** treat all government contacts as routine case priority (rejected—user accepted default urgent); treat every supplier or staffing call as urgent (rejected—creates queue noise); require supervisor manual urgency only (rejected—misses after-hours risk on tax and payroll issues).

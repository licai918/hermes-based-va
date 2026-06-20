# Copilot queue presentation for non-customer follow-up cases

**Human Intervention Case** items for **Non-Customer Contact** traffic use split Copilot presentation rules in v1.

Cases with **Contact Reason** `sales_outreach` are audit-sampled only. They do not appear in the default **Operations Dashboard** queue for **Customer Service Rep** users. **Workbench Supervisor** and **Workbench Admin** users may review them through a read-only sales-outreach audit list similar in purpose to the **Auto-Handled Audit View**.

All other non-customer cases, such as government, supplier, staffing, named recipient request, and non-customer general, appear in the same **Copilot Workbench** queue as customer **Human Intervention Case** items. Users may filter by **Contact Reason** and urgency. **Urgent Follow-up Case** items, including default-urgent government traffic and uplifted supplier or staffing cases, remain visible at the top of the default queue.

Opening a sales-outreach audit item writes a **Workbench Audit Log** entry. Recategorizing **Contact Reason** in Copilot may move a case between the default queue and the sales-outreach audit list.

**Considered options:** show every sales-outreach case in the default rep queue (rejected—queue noise); create a fully separate non-customer queue for all non-customer reasons (rejected—splits employee workflow unnecessarily); hide all non-customer cases from reps (rejected—government and supplier follow-up still needs handling).

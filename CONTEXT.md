# Hermes VA Context

This context defines the shared language for the Hermes virtual assistant used by Toee Tire customer service.

## Language

**Hermes VA**:
The virtual assistant system that handles customer-service conversations through approved profiles, knowledge, and business tools.
_Avoid_: Bot, generic AI, phone system

**Hermes Core**:
The shared text-based orchestration layer behind all Hermes profiles.
_Avoid_: Voice model, phone agent

**Hermes Profile**:
A governed operating mode of Hermes with its own audience, permissions, knowledge scope, and response policy.
_Avoid_: Separate Hermes, separate bot

**External Customer Service Profile**:
The Hermes Profile used for customer-facing phone, SMS, email, and web chat conversations.
_Avoid_: Internal assistant, supervisor agent

**Internal Copilot Profile**:
The Hermes Profile used by employees to review context, draft responses, and decide next actions.
_Avoid_: Customer-facing agent

**Supervisor Admin Profile**:
The Hermes Profile used by authorized supervisors to manage knowledge, policies, campaigns, quality review, and profile configuration.
_Avoid_: Regular copilot

**Voice Gateway**:
The channel layer that turns phone audio into text for Hermes and turns Hermes text replies back into speech.
_Avoid_: Hermes Core, LLM

**KnowledgeOps**:
The internal governance process for drafting, reviewing, publishing, evaluating, and rolling back approved Hermes knowledge.
_Avoid_: Customer training, automatic learning

**Verified Customer**:
A caller whose inbound phone number matches a phone number stored on a Shopify Customer record.
_Avoid_: Caller, phone number owner, manually verified customer

**Phone Match Verification**:
The first-version identity check that treats a matching inbound phone number as sufficient to access that Shopify Customer's allowed information and low-risk actions.
_Avoid_: Multi-factor verification, knowledge-based authentication

**Registered Phone**:
The phone number stored on a Shopify Customer record for a Toee Tire account. In normal operation this value is unique across Shopify Customers.
_Avoid_: Any caller phone, alternate contact number

**Ambiguous Phone Match**:
A situation where one inbound phone number matches more than one Shopify Customer **Registered Phone** record.
_Avoid_: Duplicate account, shared phone by default

**Unmatched Caller**:
A caller whose inbound phone number does not match any Shopify Customer **Registered Phone**.
_Avoid_: Unverified customer, guest caller

**Low-Risk Customer Service Action**:
A customer-facing action Hermes may complete without changing accounting, refunds, pricing, inventory, or delivery commitments.
_Avoid_: Admin action, account adjustment

**Follow-up Case**:
A record created for a human employee to review and resolve a customer request that Hermes should not complete automatically.
_Avoid_: Ticket if it implies a separate helpdesk system

**Email Link Failure**:
A state where a **Verified Customer** cannot be linked from Shopify to QBO because the Shopify email is missing or has no matching **QBO Customer**.
_Avoid_: Accounting lookup failure, partial verification

**Payment Link**:
A secure Square-hosted link sent to a customer so they can pay without sharing card details with Hermes.
_Avoid_: Card collection, phone payment

**Registered Contact**:
An existing phone number or email already stored on the matched Shopify Customer record.
_Avoid_: Verbal contact request, temporary contact

**Shopify Customer**:
The customer record in Shopify used for orders, contact data, and phone-based verification.
_Avoid_: QBO customer, caller

**QBO Customer**:
The customer record in QuickBooks Online used for invoices, balances, and accounts receivable.
_Avoid_: Shopify customer, caller

**Identity Graph**:
The mapping layer that links channel identities and business-system customer records inside Hermes.
_Avoid_: CRM, customer database

**Customer Email Link**:
The email address used as the sole cross-system identifier between a **Shopify Customer** and a **QBO Customer**.
_Avoid_: Phone match, company-name match

## Relationships

- **Hermes VA** has one **Hermes Core**.
- **Hermes Core** serves one or more **Hermes Profiles**.
- **External Customer Service Profile**, **Internal Copilot Profile**, and **Supervisor Admin Profile** are **Hermes Profiles**.
- **Voice Gateway** provides audio input and output for the **External Customer Service Profile**.
- **KnowledgeOps** controls what approved knowledge the **Hermes Core** can use.
- A **Verified Customer** is identified through **Phone Match Verification** against a Shopify Customer **Registered Phone**.
- A **Verified Customer** may receive all **External Customer Service Profile** read access and **Low-Risk Customer Service Actions** for the matched Shopify Customer.
- An **Unmatched Caller** receives no account information disclosure and creates a **Follow-up Case** instead.
- An **Ambiguous Phone Match** requires customer disambiguation before Hermes treats the caller as a **Verified Customer**.
- A **Shopify Customer** links to a **QBO Customer** only through the **Customer Email Link**.
- Hermes uses the matched **Shopify Customer** email to resolve the corresponding **QBO Customer** for accounting reads.
- An **Email Link Failure** allows Shopify order and delivery answers, but blocks QBO accounting disclosure and creates a **Follow-up Case**.
- A request outside **Low-Risk Customer Service Action** boundaries creates a **Follow-up Case**.
- A **Payment Link** is a **Low-Risk Customer Service Action** only when it does not require Hermes to handle card details.
- A **Payment Link** may be sent only to a **Registered Contact** on the matched Shopify Customer.
- A verbal request to send a **Payment Link** to a new phone number or email creates a **Follow-up Case**.

## Example dialogue

> **Dev:** "Should the phone AI answer billing questions directly?"
> **Domain expert:** "The **External Customer Service Profile** can answer only after verification and only from approved knowledge or read-only accounting tools."

> **Dev:** "Can customer calls train Hermes?"
> **Domain expert:** "No. Calls can create review items, but **KnowledgeOps** decides what becomes approved knowledge."

> **Dev:** "How do we verify a customer on the after-hours phone line?"
> **Domain expert:** "If the inbound phone number matches a Shopify Customer **Registered Phone**, that caller is a **Verified Customer** through **Phone Match Verification**."

> **Dev:** "What if the caller's phone does not match?"
> **Domain expert:** "They are an **Unmatched Caller**. Hermes discloses no account data, creates a **Follow-up Case**, and tells them to call back from their Toee Tire **Registered Phone** if they want account access."

> **Dev:** "What if one phone matches multiple Shopify customers?"
> **Domain expert:** "That is an **Ambiguous Phone Match**. Hermes asks for disambiguation such as company name, order number, or invoice number. If still ambiguous, it creates a **Follow-up Case**."

> **Dev:** "After verification, can Hermes adjust an overdue invoice?"
> **Domain expert:** "No. Even for a **Verified Customer**, adjusting accounting is not a **Low-Risk Customer Service Action**; Hermes should create a **Follow-up Case**."

> **Dev:** "How does Hermes connect Shopify and QBO for AR questions?"
> **Domain expert:** "Only through the **Customer Email Link**. Phone verification identifies the **Shopify Customer**; Hermes then uses that customer's email to find the **QBO Customer**."

> **Dev:** "What if the Shopify email is missing or has no QBO match?"
> **Domain expert:** "That is an **Email Link Failure**. Hermes may still answer Shopify order and delivery questions, but accounting answers are blocked and a **Follow-up Case** is created."

> **Dev:** "Can Hermes text a payment link to a number the caller gives on the phone?"
> **Domain expert:** "No. A **Payment Link** may be sent only to a **Registered Contact** on the matched Shopify Customer. A new contact request creates a **Follow-up Case**."

## Flagged ambiguities

- "Hermes" can mean **Hermes VA** as the whole system or **Hermes Core** as the text orchestration layer; resolved: use **Hermes VA** for the system and **Hermes Core** for the shared text brain.
- "Profile" means a governed **Hermes Profile**, not a separate deployed assistant.
- "Verified" means **Phone Match Verification** against Shopify, not manual identity proof.
- "Full permissions" for a **Verified Customer** means full external-profile access for that matched customer, but still excludes accounting changes, refunds, discounts, and other non-low-risk actions.
- **Registered Phone** is expected to be unique in Shopify, but **Ambiguous Phone Match** handling remains required as a backup control.
- **Customer Email Link** is the only approved cross-system customer identifier between Shopify and QBO.

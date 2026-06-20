# SMS opt-out handling without proactive STOP disclaimer

Hermes records SMS marketing consent and honors opt-out keywords from the first version, even before promotion outbound campaigns launch.

When a customer sends **STOP**, **UNSUBSCRIBE**, or **ARRET** on Textline, Hermes immediately records opt-out in the **Identity Graph** and stops marketing or proactive outbound texts to that number. Service responses to customer-initiated inbound inquiries may continue as governed transactional/service messages.

Hermes must **not** append proactive disclaimer text such as “Reply STOP to opt out of marketing texts” to normal customer-service replies. Opt-out language appears only when the customer has sent an opt-out keyword or when a future approved marketing template explicitly requires it.

**Considered options:** mandatory STOP footer on every Hermes SMS reply (rejected—operator preference; adds noise to service conversations); deferring opt-out storage until promotion launch (rejected—compliance gap).

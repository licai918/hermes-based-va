# SimpleTexting API v2 — condensed reference

Extracted from the official OpenAPI 3.0.1 spec at https://simpletexting.com/api/docs/v2/ (2026-07-21).

- **Base URL:** `https://api-app2.simpletexting.com/v2`
- **Auth:** `Authorization: Bearer <token>` on every request; POSTs need `Content-Type: application/json`.
- List endpoints are paged: `?page=N&size=M`, response `{content: [...], totalPages, totalElements}`.

## Campaigns

### `GET /api/campaigns` — Get all Campaigns

Get all immediate campaigns from the SimpleTexting system. Please note that none of your scheduled or recurring campaigns will be returned by this request.

Parameters:
- `page` (query) — An ordinal number of the page to return with the results of a request (with the campaigns sent from 
- `size` (query) — The number of the returned campaigns to show per page
- `accountPhone` (query) — The phone number the campaign was sent from
- `state` (query) — The current state of the immediate campaigns you wish to retrieve: - **ERROR:** Returns campaigns th
- `listNameOrId` (query) — The list name or list ID
- `startDateFrom` (query) — List campaigns starting from a certain date. The time is in ISO 8601 format.
- `startDateTo` (query) — List campaigns up to a certain date. The time is in ISO 8601 format.

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.

### `POST /api/campaigns` — Send a Campaign

Create and send a campaign.

Request body:
- `title` (string) **(required)** — Campaign title
- `listIds` (array<string>) — Lists IDs or names
- `segmentIds` (array<string>) — Segments IDs or names
- `accountPhone` (string) — Account phone, primary number is default
- `customFieldsMaxLength` (object) — Custom fields length in current campaign, overwrite default settings. See /custom-fields
- `messageTemplate` (object) **(required)** — Campaign Template
  - `mode` (string) **(required)** — one of `AUTO`, `SINGLE_SMS_STRICTLY`, `MMS_PREFERRED`
  - `subject` (string) — Subject (available for MMS)
  - `text` (string) **(required)** — Text body
  - `unsubscribeText` (string) — Custom unsubscribe message will be appended to the message text. A default message will be appended if not specified.
  - `fallbackText` (string) — Custom fallback text if MMS cannot be received. Should contain '[url=%%fallback_link%%]' placeholder that will be replaced with a link to the message
  - `fallbackUnsubscribeText` (string) — Custom unsubscribe message will be appended to the fallback text. A default message will be appended if not specified.
  - `mediaItems` (array<string>) — List of MMS media URLs for temporal storing or media items IDs
  - `mode` (string) **(required)** — one of `AUTO`, `SINGLE_SMS_STRICTLY`, `MMS_PREFERRED`
  - `subject` (string) — Subject (available for MMS)
  - `text` (string) **(required)** — Text body
  - `unsubscribeText` (string) — Custom unsubscribe message will be appended to the message text. A default message will be appended if not specified.
  - `fallbackText` (string) — Custom fallback text if MMS cannot be received. Should contain '[url=%%fallback_link%%]' placeholder that will be replaced with a link to the message
  - `fallbackUnsubscribeText` (string) — Custom unsubscribe message will be appended to the fallback text. A default message will be appended if not specified.
  - `mediaItems` (array<string>) — List of MMS media URLs for temporal storing or media items IDs

Response 201:
- `id` (string) — ID of item in hexadecimal format.

### `GET /api/campaigns/{campaignId}` — Get a Campaign

Get a campaign via its unique ID.

Parameters:
- `campaignId` (path, required) — Campaign ID in hexadecimal format

Response 200:
- `campaignId` (string) **(required)** — Existing campaign ID in hexadecimal format
- `title` (string) **(required)** — Campaign name
- `accountPhone` (string) **(required)** — Number the campaign was sent from
- `customFieldsMaxLength` (object) — Custom fields length in current campaign
- `state` (string) **(required)** — one of `PAUSED`, `SENDING`, `COMPLETED`, `ERROR`, `MONITORING`
- `lists` (array<object>) **(required)** — List of lists campaign was sent to
- `segments` (array<object>) **(required)** — List of segments campaign was sent to
- `created` (string) — Created timestamp. The time is in ISO 8601 format.
- `modified` (string) — Modified timestamp. The time is in ISO 8601 format.
- `started` (string) — Started timestamp. The time is in ISO 8601 format.
- `finished` (string) — Finished timestamp. The time is in ISO 8601 format.
- `messageTemplate` (object) **(required)** — Template of message sent


## Messages

### `GET /api/messages` — Get all Messages

Retrieves a list of all messages sent to a specific contact from a specific number on your account.

Parameters:
- `page` (query) — An ordinal number of the page to return with the results of a request (with the messages of the give
- `size` (query) — The number of the returned messages to show per page
- `accountPhone` (query) — The phone number on your account the messages were sent to. If blank, the request will return the me
- `since` (query) — First sent/received timestamp. The time is in ISO 8601 format.
- `contactPhone` (query) — The contact's phone number

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.

### `POST /api/messages` — Send a Message

Send either an MMS or SMS message to a contact. Use this programmatically to send to multiple contacts. If the message contains a link from a common third-party link shortener such as bit.ly, it will appear from our URL shortener instead and occupy 20 characters. Learn more. There are limitations on

Request body:
- `contactPhone` (string) **(required)** — Contact's phone
- `accountPhone` (string) — The account phone to send from. If this field is left blank, the primary account number will be used as a default
- `mode` (string) **(required)** — one of `AUTO`, `SINGLE_SMS_STRICTLY`, `MMS_PREFERRED`
- `subject` (string) — MMS Subject (available for MMS)
- `text` (string) **(required)** — Text Body
- `fallbackText` (string) — Custom fallback text if MMS cannot be received. Should contain '[url=%%fallback_link%%]' placeholder that will be replaced with a link to the message
- `mediaItems` (array<string>) — List of MMS media URLs for temporal storing or media items IDs

Response 201:
- `id` (string)
- `credits` (integer)

### `POST /api/messages/evaluate` — Evaluate a Message

Evaluate the body of your message before sending it to a contact or contacts.

Request body:
- `mode` (string) **(required)** — one of `AUTO`, `SINGLE_SMS_STRICTLY`, `MMS_PREFERRED`
- `subject` (string) — MMS Subject (available for MMS)
- `text` (string) **(required)** — Text Body
- `fallbackText` (string) — A custom fallback text if a contact can't receive an MMS message. It should contain a `[url=%%fallback_link%%]` placeholder that will be replaced with a link to
- `mediaItems` (array<string>) — List of MMS media URLs for temporal storing or media items IDs

Response 201:
- `detectedCategory` (string) — one of `SMS`, `MMS`, `EXTENDED_SMS`
- `length` (integer) — The message length in characters
- `remains` (integer) — The remaining characters
- `maxLength` (integer) — The maximum message length in characters with the current message type and encoding
- `unicode` (boolean) — Returns true if there is some number of Latin-1 or GSM-7 characters present
- `sumOfCredits` (integer) — How much credits message will cost
- `warnings` (array<string>) — A list of warning messages if present
- `errors` (array<string>) — List of error messages if present

### `GET /api/messages/{messageId}` — Get a Message

Retrieve a specific message from the system via its message ID.

Parameters:
- `messageId` (path, required) — Message ID in hexadecimal format

Response 200:
- `id` (string) — Message ID in hexadecimal format
- `subject` (string) — Subject (available for MMS)
- `text` (string) — Text
- `contactPhone` (string) — Contact phone
- `accountPhone` (string) — Account phone (primary or secondary)
- `directionType` (string) — one of `MT`, `MO`
- `timestamp` (string) — Time of sending. The time is in ISO 8601 format.
- `referenceType` (string) — Reference type (available only for MT (Mobile-Terminating) messages)
- `category` (string) — one of `SMS`, `MMS`, `EXTENDED_SMS`
- `mediaItems` (array<string>) — List of MMS media descriptors: ID in hexadecimal format for st-stored file


## Media Items

### `GET /api/mediaitems` — Get Media Items

This endpoint allows you to retrieve all Media Items.

Parameters:
- `page` (query) — Number of pages
- `size` (query) — Page size

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.

### `POST /api/mediaitems/loadByLink` — Upload Media Using a URL

This endpoint allows you to upload media via a URL so that you can send it in a message to a contact.

Request body:
- `link` (string) **(required)** — The URL you will upload your media to

Parameters:
- `shared` (query) — Define whether a media file is shared with teammates

Response 200:
- `id` (string) — Existing media ID in hexadecimal format
- `createdDate` (string) — When the media was created. The time is in ISO 8601 format.
- `name` (string) — File name
- `gallery` (string) — Gallery
- `size` (integer) — File size
- `status` (string) — Status of the file
- `link` (string) — Location of file
- `contentType` (string) — File media type
- `ext` (string) — File extension
- `canDelete` (boolean) — Ability to delete file

### `POST /api/mediaitems/upload` — Upload Media

Upload a media file from a local directory to SimpleTexting.

Parameters:
- `shared` (query) — Define whether a media file is shared with teammates

Response 200:
- `id` (string) — Existing media ID in hexadecimal format
- `createdDate` (string) — When the media was created. The time is in ISO 8601 format.
- `name` (string) — File name
- `gallery` (string) — Gallery
- `size` (integer) — File size
- `status` (string) — Status of the file
- `link` (string) — Location of file
- `contentType` (string) — File media type
- `ext` (string) — File extension
- `canDelete` (boolean) — Ability to delete file

### `DELETE /api/mediaitems/{mediaItemId}` — Delete Media

Remove media that you have previously uploaded to SimpleTexting.

Parameters:
- `mediaItemId` (path, required) — The mediaItemId in hexadecimal format

### `GET /api/mediaitems/{mediaItemId}` — Get Media Item

Parameters:
- `mediaItemId` (path, required) — Media item ID in hexadecimal format

Response 200:
- `id` (string) — Existing media ID in hexadecimal format
- `createdDate` (string) — When the media was created. The time is in ISO 8601 format.
- `name` (string) — File name
- `gallery` (string) — Gallery
- `size` (integer) — File size
- `status` (string) — Status of the file
- `link` (string) — Location of file
- `contentType` (string) — File media type
- `ext` (string) — File extension
- `canDelete` (boolean) — Ability to delete file


## Contacts

### `GET /api/contacts` — Get all Contacts

For a given account, return all contacts that have been created in the account. A paginated list of contacts will be returned to you:

Parameters:
- `page` (query) — An ordinal number of the page to return with the results of a request (with the contacts of the give
- `size` (query) — The number of the returned contacts to show per page
- `since` (query) — List contacts updated since a specified date. The time is in ISO 8601 format.
- `direction` (query) — Specify the sort order of your results. By default, results are sorted by the 'updated' field: - **A

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.

### `POST /api/contacts` — Create a Contact

Create a new contact and add them to a specific list.

Request body:
- `contactPhone` (string) — Contact's phone number
- `firstName` (string) — Contact's first name
- `lastName` (string) — Contact's last name
- `email` (string) — Contact's email
- `birthday` (string) — Contact's birthday in format: yyyy-mm-dd
- `customFields` (object) — Object that contains custom field values, where you should use a Name or a Merge tag in a property name and a field value as a property value. To find a merge t
  - `Merge tag` (string)
  - `Merge tag` (string)
- `comment` (string) — Notes about the contact.
- `listIds` (array<string>) — All the lists (List IDs or names) to add the contact to or replace.

Parameters:
- `upsert` (query) — If a contact already exists with the phone number in your request body, the contact will be updated 
- `listsReplacement` (query) — If listsReplacement is set to true, a contact will be removed from their existing list. If set to fa

Response 201:
- `id` (string) — ID of item in hexadecimal format.

### `DELETE /api/contacts/{contactIdOrNumber}` — Delete a Contact

Delete a contact via their unique ID or phone.

Parameters:
- `contactIdOrNumber` (path, required) — Contact ID in hexadecimal format or phone number

### `GET /api/contacts/{contactIdOrNumber}` — Get a Contact

Get a contact via their unique ID or phone number. Phone number is the preferred parameter for this call.

Parameters:
- `contactIdOrNumber` (path, required) — Phone number (preferred) or Contact ID in hexadecimal format

Response 200:
- `contactId` (string) **(required)** — Existing contact ID in hexadecimal format
- `contactPhone` (string) **(required)** — Contact's phone number
- `firstName` (string) **(required)** — Contact's first name
- `lastName` (string) **(required)** — Contact's last name
- `email` (string) **(required)** — Contact's email
- `birthday` (string) — Contact's birthday in format (yyyy-mm-dd)
- `lists` (array<object>) — Array of objects (Contact list) All the lists where the contact is stored subscriptionStatus
- `customFields` (object) — Object that contains custom field values, where you should use a Name or a Merge tag in a property name and a field value as a property value. To find a merge t
  - `Merge tag` (string)
  - `Merge tag` (string)
- `comment` (string) — Notes about the contact
- `subscriptionStatus` (string) — one of `OPT_IN`, `OPT_OUT`, `WAIT_SMS_CONFIRMATION`, `REJECT_CONFIRMATION`

### `PUT /api/contacts/{contactIdOrNumber}` — Update a Contact

Update a contact’s phone number or any other field.

Request body:
- `contactPhone` (string) — Contact's phone number
- `firstName` (string) — Contact's first name
- `lastName` (string) — Contact's last name
- `email` (string) — Contact's email
- `birthday` (string) — Contact's birthday in format: yyyy-mm-dd
- `customFields` (object) — Object that contains custom field values, where you should use a Name or a Merge tag in a property name and a field value as a property value. To find a merge t
  - `Merge tag` (string)
  - `Merge tag` (string)
- `comment` (string) — Notes about the contact.
- `listIds` (array<string>) — All the lists (List IDs or names) to add the contact to or replace.

Parameters:
- `contactIdOrNumber` (path, required) — Contact ID in hexadecimal format or the contact's phone number.
- `upsert` (query) — If a contact already exists with the phone number in your request body, the contact will be updated 
- `listsReplacement` (query) — If listsReplacement is set to true, a contact will be removed from their existing list. If set to fa

Response 200:
- `id` (string) — ID of item in hexadecimal format.


## Contacts - Batch Operations

### `POST /api/contacts-batch/batch-delete` — Delete a Group of Contacts

Delete a group of contacts from SimpleTexting using their phone numbers.

Request body:
- `contactPhones` (array<string>) **(required)**

Response 201:
- `results` (array<object>) — List of the deleted contacts

### `POST /api/contacts-batch/batch-update` — Update a Group of Contacts

Update multiple fields at once for a batch of contacts. You can update their first name, last name, emails, lists, and more.

Request body:
- `listsReplacement` (boolean) — If listsReplacement is set to true, a contact will be removed from their existing list. If set to false, a contact will be added to a new list and stay in their
- `updates` (array<object>) **(required)** — List of updates for contacts

Response 201:
- `id` (string) — ID of item in hexadecimal format.

### `GET /api/contacts-batch/batch-update/{taskId}` — Get the Result of a Batch Update Task

Return the result of a batch update by the task id.

Parameters:
- `taskId` (path, required) — The ID of the task for the batch update

Response 201:
- `status` (string) — one of `IN_PROGRESS`, `DONE`
- `results` (array<object>) — List of update results
- `requestedCount` (integer) — Contacts count that were requested to be updated/added
- `processedCount` (integer) — Contacts count that were updated/added


## Contact Lists

### `GET /api/contact-lists` — Get all Lists

Retrieves all lists from your SimpleTexting account.

Parameters:
- `page` (query) — An ordinal number of the page to return with the results of a request (with the lists of the given a
- `size` (query) — The number of the returned lists to show per page

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.

### `POST /api/contact-lists` — Create a List

This endpoint is used to create a new contact list in a given SimpleTexting account.

Request body:
- `name` (string) **(required)** — A list name containing less than 42 characters

Response 201:
- `id` (string) — ID of item in hexadecimal format.

### `DELETE /api/contact-lists/{listIdOrName}` — Delete a List

Delete an existing list using the list ID or name.

Parameters:
- `listIdOrName` (path, required) — List ID in hexadecimal format or name.

### `GET /api/contact-lists/{listIdOrName}` — Get a List

Return a contact list by its unique list ID or name.

Parameters:
- `listIdOrName` (path, required) — List ID in hexadecimal format or name.

Response 200:
- `listId` (string) — List ID in hexadecimal format
- `name` (string) — The list name
- `created` (string) — When the list was created. The time is in ISO 8601 format.
- `updated` (string) — When the list was updated. The time is in ISO 8601 format.
- `description` (string) — Title is present when list is created automatically by a keyword via the dashboard, otherwise defaults to null
- `totalContactsCount` (integer) — The number of contacts
- `activeContactsCount` (integer) — The number of active contacts
- `invalidContactsCount` (integer) — The number of invalid contacts
- `unsubscribedContactsCount` (integer) — The number of unsubscribed contacts
- `keywords` (array<string>) — Keywords associated with the list

### `POST /api/contact-lists/{listIdOrName}/contacts` — Add Contact To List

Add contact to specified list.

Request body:
- `contactPhoneOrId` (string) — Contact ID in hexadecimal format or the contact's phone number.

Parameters:
- `listIdOrName` (path, required) — List ID or name to add the contact.

### `DELETE /api/contact-lists/{listIdOrName}/contacts/{contactPhoneOrId}` — Remove Contact From List

Remove contact from specified list.

Parameters:
- `listIdOrName` (path, required) — List ID or name to remove the contact from.
- `contactPhoneOrId` (path, required) — Contact ID in hexadecimal format or the contact's phone number.

### `PUT /api/contact-lists/{listId}` — Update a List Name

Update the name of an existing list.

Request body:
- `name` (string) **(required)** — A list name containing less than 42 characters

Parameters:
- `listId` (path, required) — List ID in hexadecimal format or name.

Response 200:
- `id` (string) — ID of item in hexadecimal format.


## Contact Segments

### `GET /api/contact-segments` — Get all Segments

Retrieves all segments from your SimpleTexting account.

Parameters:
- `page` (query) — An ordinal number of the page to return with the results of a request (with the segments of the give
- `size` (query) — The number of the returned segments to show per page

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.


## Custom Fields

### `GET /api/custom-fields` — Get all Custom Fields

This endpoint allows you to retrieve all custom fields.

Parameters:
- `page` (query) — An ordinal number of the page to return with the results of a request (with the custom fields of the
- `size` (query) — The number of the returned custom fields to show per page

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.


## Webhooks

### `GET /api/webhooks` — Get all Webhooks

Retrieve all the webhooks that you've created.

Parameters:
- `page` (query) — An ordinal number of the page to return with the results of a request (with the webhooks of the give
- `size` (query) — The number of the returned webhooks to show per page

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.

### `POST /api/webhooks` — Create a Webhook

Create a new webhook from scratch.

Request body:
- `url` (string) **(required)** — The URL for handling a POST request
- `triggers` (array<string>) **(required)** — Trigger a webhook based on a specific platform event: - **INCOMING_MESSAGE:** Trigger a webhook event based on an incoming message - **OUTGOING_MESSAGE:** Trigg
- `requestPerSecLimit` (integer) — The maximum number of requests that can be sent within a second
- `accountPhone` (string) — Optional: requests will come exclusively for the specified account phone number
- `contactPhone` (string) — Optional: requests will come exclusively for the specified contact's phone number

Response 201:
- `id` (string) — ID of item in hexadecimal format.

### `DELETE /api/webhooks/{webhookId}` — Delete a Webhook

Delete an existing Webhook by its unique ID.

Parameters:
- `webhookId` (path, required) — Webhook ID in hexadecimal format

### `PUT /api/webhooks/{webhookId}` — Update a Webhook

Update an existing webhook using its unique ID.

Request body:
- `url` (string) **(required)** — The URL for handling a POST request
- `triggers` (array<string>) **(required)** — Trigger a webhook based on a specific platform event: - **INCOMING_MESSAGE:** Trigger a webhook event based on an incoming message - **OUTGOING_MESSAGE:** Trigg
- `requestPerSecLimit` (integer) — The maximum number of requests that can be sent within a second
- `accountPhone` (string) — Optional: requests will come exclusively for the specified account phone number
- `contactPhone` (string) — Optional: requests will come exclusively for the specified contact's phone number

Parameters:
- `webhookId` (path, required) — Webhook ID in hexadecimal format

Response 200:
- `id` (string) — ID of item in hexadecimal format.


## Webhook Reports

### `POST /report/delivery` — Delivery/Non Delivered Message Report

Triggers when an outgoing message is reported as delivered or undelivered by the carrier.

Request body:
- `reportId` (string) — Unique report ID in hexadecimal format
- `webhookId` (string) — Webhook ID in hexadecimal format
- `type` (string) — one of `INCOMING_MESSAGE`, `OUTGOING_MESSAGE`, `DELIVERY_REPORT`, `NON_DELIVERED_REPORT`, `UNSUBSCRIBE_REPORT`
- `values` (object) — Report content
  - `messageId` (string) — Message ID in hexadecimal format
  - `category` (string) — Message category: - **SMS:** SMS are regular texts, 160 characters or below - **MMS:** Multimedia messages. Messages over 306 characters, or with media attached
  - `referenceType` (string) — Reference type (available only for MT messages)
  - `accountPhone` (string) — Account phone (primary or secondary)
  - `contactPhone` (string) — Contact phone
  - `carrier` (string) — Name of carrier
  - `messageId` (string) — Message ID in hexadecimal format
  - `category` (string) — Message category: - **SMS:** SMS are regular texts, 160 characters or below - **MMS:** Multimedia messages. Messages over 306 characters, or with media attached
  - `referenceType` (string) — Reference type (available only for MT messages)
  - `accountPhone` (string) — Account phone (primary or secondary)
  - `contactPhone` (string) — Contact phone
  - `carrier` (string) — Name of carrier

### `POST /report/incoming` — Incoming/Outgoing Message Report

Triggers when an outgoing message or incoming message is handled.

Request body:
- `reportId` (string) — Unique report ID in hexadecimal format
- `webhookId` (string) — Webhook ID in hexadecimal format
- `type` (string) — one of `INCOMING_MESSAGE`, `OUTGOING_MESSAGE`, `DELIVERY_REPORT`, `NON_DELIVERED_REPORT`, `UNSUBSCRIBE_REPORT`
- `values` (object) — Report content
  - `messageId` (string) — Message ID in hexadecimal format
  - `subject` (string) — Subject (available for MMS)
  - `mediaItems` (array<string>) — List of MMS media descriptors: ID in hexadecimal format for st-stored file
  - `text` (string) — Text
  - `accountPhone` (string) — Account phone (primary or secondary)
  - `contactPhone` (string) — Contact phone
  - `timestamp` (string) — Time of sending. The time is in ISO 8601 format.
  - `category` (string) — Message category: - **SMS:** SMS are regular texts, 160 characters or below - **MMS:** Multimedia messages. Messages over 306 characters, or with media attached
  - `referenceType` (string) — Reference type (available only for MT messages)
  - `messageId` (string) — Message ID in hexadecimal format
  - `subject` (string) — Subject (available for MMS)
  - `mediaItems` (array<string>) — List of MMS media descriptors: ID in hexadecimal format for st-stored file
  - `text` (string) — Text
  - `accountPhone` (string) — Account phone (primary or secondary)
  - `contactPhone` (string) — Contact phone
  - `timestamp` (string) — Time of sending. The time is in ISO 8601 format.
  - `category` (string) — Message category: - **SMS:** SMS are regular texts, 160 characters or below - **MMS:** Multimedia messages. Messages over 306 characters, or with media attached
  - `referenceType` (string) — Reference type (available only for MT messages)

### `POST /report/unsubscribe` — Unsubscribe Report

Triggers when a client sends STOP to your number.

Request body:
- `reportId` (string) — Unique report ID in hexadecimal format
- `webhookId` (string) — Webhook ID in hexadecimal format
- `type` (string) — one of `INCOMING_MESSAGE`, `OUTGOING_MESSAGE`, `DELIVERY_REPORT`, `NON_DELIVERED_REPORT`, `UNSUBSCRIBE_REPORT`
- `values` (object) — Report content
  - `contactId` (string) — Contact id in hexadecimal format
  - `phone` (string) — Contact phone
  - `contactId` (string) — Contact id in hexadecimal format
  - `phone` (string) — Contact phone


## Tenant

### `GET /api/tenant` — Get general information

Retrieves a general information about account.

Response 200:
- `email` (string)


## Tenant phones

### `GET /api/phones` — Get all phones

Retrieve all phone numbers for account.

Parameters:
- `page` (query) — The number of phone numbers returned with each request
- `size` (query) — The size of the page

Response 200:
- `content` (array<object>) — Page content and number of elements is restricted by page size.
- `totalPages` (integer) — The total number of pages. This is the number of elements divided by the page size.
- `totalElements` (integer) — Total number of elements.


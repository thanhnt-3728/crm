# Personal data erasure

When a person asks us to delete their personal data (CCPA "right to delete"), the
request is logged in the CRM and erased there after a second person approves it.

## Who does what

| Step | Who | Where |
|---|---|---|
| Log the request on the person's behalf | Whoever received it (any Sales User / Sales Manager who can see the record) | Lead page → shield button, or Contact page → **Request erasure** |
| Acknowledge receipt (by **Acknowledge By**, 10 business days) | Privacy team, outside the CRM; record the date in **Acknowledged On** | Desk: `/app/crm-data-erasure-request` |
| Approve and erase, or reject | Someone with the **CRM Privacy Officer** role who did **not** log the request | Desk form: **Preview**, **Approve & Erase**, **Reject** |
| Respond to the person (by **Respond By**, 45 calendar days) | Privacy team, outside the CRM | |

Sales Managers cannot approve. A Privacy Officer cannot approve a request they logged.
Give the Privacy team the `CRM Privacy Officer` role in User settings (the role is
created by `bench migrate`).

## What "erase" does

The person is found from the Lead and/or Contact on the request, plus every other lead
or contact with the same email address, plus every deal created from those leads or
listing those contacts.

| Record | What happens | Why |
|---|---|---|
| Lead | Kept. Name, email, phones, gender, job title, image, social links, Facebook ids cleared; name becomes `Content erased <request>` | Lead counts, conversion and time-to-close stay the same |
| Deal | Kept with status, values, dates, owner, organization, products. Person is removed from Contacts (another contact becomes primary); copied name fields cleared; Lost Notes and Next Step replaced | Pipeline and revenue stay the same |
| Contact | Deleted permanently (no Deleted Document copy), with its image and any address nobody else uses | Its docname is the person's name |
| Notes, comments, tasks, emails, WhatsApp messages, notifications, assignments on those leads/deals | Kept; text (and titles/subjects) replaced with `Content erased <request>`, **whether or not it mentions the person** | Agreed with Privacy: no per-item review |
| Emails anywhere that the person sent or received | Same as above; their address replaced with `erased@erased.invalid`; attachments deleted | |
| Call logs on those leads/deals or with their number | Kept; their number and recording link cleared | |
| Version history | Removed for the lead and erased activity; on deals only the entries that recorded the person's details | Versions keep old values |
| Outgoing mail queue, Deleted Document copies holding their email | Deleted | |
| Search index | Erased activity removed | |
| Organization | Untouched | The company is not the subject |

The request itself keeps the person's name and email as the record of the request.

## Not covered

- Backups: handled by the existing backup procedure if one is ever restored.
- Call recordings stored at Twilio/Exotel (only the link is cleared).
- Copies pushed to ERPNext by the ERPNext integration.
- The person's WhatsApp profile (`WA Profile`) and email still sitting in the mail server.
- Error logs and access logs.

## Code

| File | Role |
|---|---|
| `crm/fcrm/doctype/crm_data_erasure_request/crm_data_erasure_request.py` | Request lifecycle, deadlines, who may decide |
| `crm/fcrm/doctype/crm_data_erasure_request/erasure.py` | Finds the person's records and erases them, in one transaction |
| `crm/fcrm/doctype/crm_data_erasure_request/crm_data_erasure_request.js` | Desk buttons for the Privacy team |
| `frontend/src/components/Modals/DataErasureRequestModal.vue` | "Request data erasure" dialog on Lead and Contact pages |

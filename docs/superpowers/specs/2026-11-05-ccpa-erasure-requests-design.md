# Personal data erasure requests (CCPA) — Design

Date: 2026-11-05
Status: Draft for approval
Sources: `#revops-product` Slack thread (Priya Nair, Tyler Brandt, Sam Kowalczyk, Dana Okafor) and the Marisol Vega email chain (Oct 26, 2026); follow-up decisions with the requester in this design conversation.

Markers used below: **[decided]** = the requester decided it. **[my call]** = proposed by the designer and not objected to, or settled during the write-up. Unmarked items restate facts.

---

## 1. Why

Northpine received its first CCPA deletion request. A former lead, Marisol Vega (Sierra Foothills Dental Group), asked for all her personal information to be deleted. Since January 2023 the CCPA has covered B2B contacts, so the request is valid and more will follow. Today the CRM can't do this. Her data is spread over her lead, two deals (one still open in Negotiation), her contact, and many emails. Deleting the lead by hand leaves the rest behind and changes reports.

Legal clock per request: the request must be acknowledged within **10 business days** and answered within **45 calendar days** of receipt. For Marisol: received Oct 26, acknowledge by Nov 9, respond by Dec 10.

**Success:** a rep logs a request from wherever they received it. Compliance signs off, seeing exactly what will happen. The CRM erases the person everywhere it holds them in one irreversible action, without changing a single pipeline or revenue number. Nobody misses a deadline, because the CRM warns before it falls due. Once the request closes, the CRM keeps only the minimal log the law requires, plus a block that prevents the person from being re-entered.

## 2. Goals, non-goals, anti-goals

**Goals**
- Log an erasure request on the person's behalf, from a lead, a contact, a deal, or a blank form.
- Track the acknowledgment and response deadlines, and remind people before either is missed.
- Require sign-off by a Compliance member other than the logger.
- Erase the person's identifying data everywhere the CRM holds it, keeping records whose existence feeds reports.
- Track copies held outside the CRM (e.g. Twilio recordings) as a checklist that blocks closing.
- On close, wipe the request's own identifying details and keep a 24-month log entry plus a do-not-contact entry.
- Block re-creation of an erased person, both manually and through imports.

**Non-goals**
- Requests to know, correct or opt out. These are a separate project planned for Q2 2027. The request type field exists and is always "Erasure" for now.
- Backups. **[decided]** The existing backup procedure handles any restored backup.
- Company data. The organization (e.g. Sierra Foothills Dental Group) is not the person and stays untouched. **[decided]**
- Automatically deleting data at external providers. The CRM only tracks it via the checklist.
- Undo. **[decided]** Erasure is irreversible.
- Passing mentions of the person inside other records, e.g. a note on a deal saying "Marisol prefers Tuesdays". **[decided]** This is not searched for or ticked off individually. The outcome email lists it as a known limitation (see 5.10).
- The ERPNext integration (customers, quotations, sales orders). **[decided]** It's not used at Northpine and is left out.
- The slow kanban/list views mentioned in the thread are unrelated.

**Anti-goals (failure even if it "works")**
- Any pipeline, revenue, funnel or count on the dashboard changes after an erasure. Finance's board deck pulls from these.
- One person can erase someone alone. Reps never erase. The logger never approves. Sales managers and admins can't approve unless they hold the Compliance role.
- Personal data quietly survives somewhere the CRM controls, such as change history, Frappe's deleted-document copies, a custom field, or a partially blanked email.
- A deadline is missed without anyone being warned beforehand.

## 3. Constraints

- Frappe CRM: Vue 3 + frappe-ui frontend (`frontend/`) and a Frappe Python backend (`crm/`). All user-facing screens are in the CRM UI, not Frappe Desk. Tyler must be able to log a request from the lead page. **[my call]**
- Dashboard numbers (`crm/api/dashboard.py`) count leads and deals and sum deal values by status, source, territory, salesperson and date. So **leads and deals are never deleted. Their personal fields are blanked in place.** Status, source, territory, owner, dates, values, products, status-change logs and organization stay as they are.
- Admins can add custom fields to leads, deals and contacts (Settings → Custom Fields). Erasure must not silently miss them.
- `CRM Lead.first_name` is mandatory. Blanked mandatory name fields get the placeholder `Erased person <request number>`.
- Frappe keeps a full JSON copy of deleted records (`Deleted Document`) and old field values in `Version`. Both must be scrubbed.

## 4. Approaches considered

1. **Extend Frappe's built-in Personal Data Deletion Request.** It's built for website users confirming by an emailed link, has one admin approval, deletes rows instead of blanking them, and has no deadlines, checklist or do-not-contact list. We'd override nearly all of it. Rejected.
2. **Fixed erasure rules in code.** Simplest and fully testable, but a custom field like "Personal mobile" added later would be skipped silently until a developer notices. Rejected, because it fails without anyone noticing.
3. **Fixed rules in code for the hidden places, plus an admin-editable list of personal fields for leads, contacts and deals.** Pre-filled, extendable by admins. The approval screen flags custom fields not on the list. **Chosen [decided]**, because the CRM is built to be customized and Compliance must see gaps before approving.

## 5. The design

### 5.1 Roles and settings
- New role **Compliance** (the Privacy team, which is Dana's team). Only Compliance can approve, decline, manage the checklist and close. **[decided]**
- New setting **Head of Compliance** (a User). Receives day-40 escalations. **[decided]**
- New setting **Personal fields** list: (doctype, field) rows for CRM Lead, CRM Deal, Contact (and its email/phone child tables), CRM Contacts (deal contact rows) and Address. It ships pre-filled with every field that identifies the person: **name (salutation, first/middle/last, full/lead name), email, phone/mobile, job title/designation, photo/image, address.** **[decided]** Admins can add rows. Gender is pre-filled as well. **[my call]** It's personal and adds nothing to reports.
- Lead/deal `linkedin`, `twitter`, `facebook`, `website` are company fields (they sit with organization logo/description) and are **not** pre-filled. **[my call]** If Compliance disagrees, they can add them to the list.
- Visibility: Compliance sees all requests. A logger sees and edits their own request in full only while it's *Logged*, so they can confirm matches. After they submit it, they see only the status and due dates. Other users don't see it. **[my call]** The request holds the original message and identifiers, which sales shouldn't browse.
- New setting **Contract retention period**, set per counsel's instruction (see 5.11). **[decided that counsel sets it; setting is my call]**

### 5.2 The request record
Named `PDR-.####` (e.g. `PDR-0001`). This number appears on erased placeholders and is typed to confirm. **[my call on format]**

Fields:
- Request type (always "Erasure")
- How it arrived (email, phone, web form, mail, other)
- Date received (entered by the logger; defaults to today)
- Logged by
- Requester's identifying details: name(s), email(s), phone(s), original message
- Matched records
- Checklist
- Acknowledgment sent (checkbox + date)
- Status
- Approver + approved on
- Erased on
- Date answered
- Outcome
- Denial reason

**Statuses:**
```
Logged → Awaiting sign-off → Erased → Closed
             ↑   ↓     ↘ Declined → Closed
            On Hold
```
- *Logged*: the logger is still confirming matches. *Awaiting sign-off*: matches confirmed and submitted to Compliance.
- *On Hold* **[decided]**: the person is a contact on an open deal. An open deal is one whose status type is Open, Ongoing or On Hold, not Won or Lost.
  - Each such deal's owner is notified (CRM notification + email) to remove her from the deal or close it.
  - The 45-day clock and all reminders keep running.
  - The check runs on submission and again at approval. When no confirmed person is on an open deal any more, the request returns to *Awaiting sign-off* automatically, checked on deal save. **[my call on mechanics]**
  - Approval is impossible while *On Hold*.
- *Declined* requires a written reason (e.g. identity not verifiable, a legal exemption). **[my call, accepted]**
- *Closed* requires a date answered, an outcome (completed / partly completed / denied), and a reason if denied. It also requires every checklist item to be ticked. **[decided]** A request closes when Compliance records the date answered, because until then the CRM needs the requester's email to reply. **[my call, accepted]**

### 5.3 Logging and matching
- Entry points: a "Request erasure" action on lead, contact and deal pages (prefills identifiers from that record), and a blank form (from the requests list) for requesters who aren't in the CRM under the address they wrote from. **[decided]** Any CRM user can log.
- The CRM suggests matches: leads, contacts and deals whose personal-field emails or phones match any identifier entered, plus records linked to a confirmed match (lead → deals converted from it; contact → deals listing it in contacts). **[my call, accepted]**
- The logger or Compliance confirms which matches are the person. **Only confirmed records are erased.** The record the request was started from is pre-confirmed.
- **Confirmed identifiers [my call].** The request has its own list of the person's emails and phones:
  - It's built from what was typed on the request plus every email and phone on her confirmed lead and contact.
  - Each identifier shows how many records, emails and calls it matches.
  - The logger or Compliance can exclude one, such as a shared office line or `office@…` inbox. This stops one erasure from wiping colleagues' calls and emails and permanently blocking a shared number.
  - Only confirmed identifiers drive the email/call sweep (5.6) and the do-not-contact entries (5.9).
- Emails, calls, notes, tasks, comments and attachments are not confirmed individually. They follow from the confirmed records and confirmed identifiers (see 5.6).

### 5.4 Deadlines and days left [decided]
- **Respond by** = date received + 45 calendar days. Every open request shows "N of 45 days left". The list of open requests is sorted by days left, ascending.
- **Acknowledge by** = the 10th business day after the date received. Counting starts the day after receipt. Business days are Monday–Friday excluding US federal holidays. Check: Oct 26, 2026 → Nov 9, 2026.
- US federal holidays are computed in code from their statutory rules, including observed dates (Saturday → Friday, Sunday → Monday). **[my call]** This needs no yearly upkeep. Adding a new federal holiday is a one-line code change.

### 5.5 Reminders [decided]
Reminders run on a daily scheduler and go out only while the request is not Closed. Each is sent both as a CRM notification and as an email, once per request per reminder.
- **Acknowledgment:** if "acknowledgment sent" is unticked 3 business days before *acknowledge by*, remind all Compliance users.
- **Day 30** (received + 30): remind all Compliance users.
- **Day 40** (received + 40): alert the Head of Compliance.

If a request is logged late (e.g. received date already past day 30), the reminders that are already due go out on the next run. **[my call]**

### 5.6 What erasure does (on approval)
**The approval screen [decided]** shows three things:
1. What will be removed, each with a link and counts per kind.
2. What will be kept: the organization, deal values/status/stage, the deals' own notes/tasks/files, lead/deal records as anonymized shells, email/call/note records as placeholders, and any retained-contract entry (5.11).
3. Open checklist items, and custom fields on lead/deal/contact that are not on the personal fields list. **[my call]**

The approver types the request number to confirm. There is no undo. The approver must hold Compliance and must not be the logger. This is checked on the server, by user. **[decided]**

**Then, in one background job (all or nothing):**

| Where | What happens |
|---|---|
| Confirmed CRM Lead | Personal fields from the list are blanked. Mandatory name → `Erased person PDR-0001`. The record stays. |
| Confirmed CRM Deal (only Won/Lost by now, because open ones put the request On Hold) | **Only she is removed from it. [decided]** Her row in the deal's contacts table is anonymized (`full_name` → placeholder; email/phone blanked); the `contact` link is kept to the anonymized contact. The deal's own personal fields (`email`, `mobile_no`, `phone`, names, job title…) are blanked **only where they hold her values**. Those fields are copied from the primary contact (`set_primary_email_mobile_no` in `crm_deal.py`), so another person's data there is left alone. **[my call]** The deal's notes, tasks, comments and files stay. Values, status and stage are untouched. |
| Confirmed Contact | Personal fields blanked (names → placeholder), email and phone child rows removed, photo file deleted. The record stays so deal links hold. **[my call]** |
| Address linked to the contact | All fields blanked. **[my call]** |
| Emails (Communication) linked to her confirmed lead or contact, or with a confirmed email address as sender/recipient/CC/BCC (on deals too) | **Never deleted. [decided]** Subject and content → `Content erased PDR-0001`. Each of her addresses in sender/recipients/CC/BCC → `Erased person PDR-0001`. Same for every such email, whoever else is on it. Attachments: see Files. |
| Call logs linked to her confirmed lead or contact, or with a confirmed phone as from/to (on deals too) | Record kept. Her number → placeholder, `recording_url` cleared, linked note handled as Notes. If any had a recording, add checklist item "Delete recordings at provider (Twilio)". **[decided]** |
| Notes, tasks, comments on her confirmed lead or contact (not on deals) | Record kept, text (title/content/description) → `Content erased PDR-0001`. Task status/dates/assignee kept. **[my call, accepted; narrowed to lead/contact by the deal decision]** |
| Files attached to her confirmed lead or contact, or to the emails above (not other deal files) | File deleted. A placeholder text remains where the file was listed. **[my call, accepted]** |
| Version (change history) of confirmed records | Old/new values of personal fields replaced with the placeholder. Non-personal changes (status etc.) kept. **[my call]** |
| Deleted Document copies of her leads/contacts/deals/emails | Scrubbed the same way, or removed. **[my call]** |
| Notifications, email queue, WhatsApp messages, event participants, failed lead-sync logs and enrichment-run changes mentioning her email/phone | Text/identifiers replaced with the placeholder. |
| Search index | Affected records re-indexed. |

Status → *Erased*. The do-not-contact entry is created now, not at close. **[my call]** This keeps her blocked from the moment of erasure.

### 5.7 Checklist [decided]
- Items describe copies outside the CRM. The Twilio item is auto-added when recordings existed, and Compliance can add more for any other provider.
- Ticking an item records who ticked it and when. **[my call, accepted]** A request can't close while any item is open.

### 5.8 Close and retention [decided]
At close, the request's identifying details are wiped: names, emails, phones, original message, matched-record list and checklist text. What remains is a **log entry**, kept 24 months:
- date received
- request type
- how it arrived
- date answered
- outcome
- denial reason

After 24 months the entry is deleted automatically (daily job). **[my call]**

### 5.9 Do-not-contact and blocking [decided]
- One entry per erased email and phone, holding only a one-way scrambled form of it (keyed hash with a secret stored in settings; plain hashes of emails can be reversed by guessing). **[my call]** Before hashing, emails are lowercased and trimmed, and phones are normalized to E.164. **[my call, accepted]**
- **Block** on creating a lead, contact or deal (including its contacts rows) whose email or phone matches an entry, and on changing an existing record's email/phone to a matching value. This applies to manual entry, imports, Facebook lead sync, create-lead-from-call-log and WhatsApp lead creation. The record is not created and the CRM says this person asked to be erased. The check lives server-side in validation, so every path is covered. Existing records saved without changing those fields are not blocked. **[my call]** Otherwise a record judged "not her" that shares a value would fail on every save.
- Nothing lifts a block. If the person returns, their old email/phone stay blocked. (Acknowledged by the requester.)
- **Inbound email from a blocked or in-request address [decided].** Incoming email is never rejected, since that would break mailbox sync.
  - No lead is created from it.
  - While her request is still open, the email is attached to the request.
  - After close, it's attached to nothing, and Compliance is notified to decide what to do with it.
  - Matching on arrival uses the request's confirmed identifiers while it's open, and the do-not-contact entries afterwards.

### 5.10 Outcome email
Compliance writes and sends the answer to the requester. The CRM ships an email template, "Erasure outcome", for it. **[my call]** The template includes the known-limitation sentence **[decided]**: passing mentions of the person inside other people's records (for example a note on a deal) aren't searched for or erased.

### 5.11 Signed contract or order exception [decided]
If she signed a contract or order with Northpine, the CRM keeps **only her name and the contract reference**, for as long as counsel sets.

The CRM doesn't hold contracts itself, so this is my proposal for how it works **[my call]**:
- Before approving, Compliance enters the contract reference(s) on the request.
- At erasure, a separate **retained-contract entry** is created with her name, the reference and a delete-after date (erasure date + contract retention period).
- That entry survives close. It is deleted automatically on its delete-after date.
- Her name is otherwise erased everywhere as normal.

## 6. Left to the builder
- Doctype names and exact field layout. The settings home (new settings doctype vs. FCRM Settings).
- Where the requests list lives in the sidebar, and the visual design of the approval screen (it must contain the three sections and the typed confirmation).
- How the background job reports progress and failure. It must be all-or-nothing, and a failure leaves the request in *Awaiting sign-off* with the error shown.
- How matching queries are built, and performance on large email tables.
- Tests. Pure logic (business-day and holiday math, normalization, placeholder rules) goes in `frontend/tests/unit` or Python unit tests. Erasure and blocking get Python integration tests, including "dashboard numbers identical before and after".

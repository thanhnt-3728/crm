# Privacy Requests (Personal Data Erasure)

> **Who is this for?**
>
> - **[Reps](#for-reps-logging-a-request)**: anyone who may receive a request from a customer or lead.
> - **[Compliance](#for-compliance-working-a-request)**: the team that signs off, erases and answers.
> - **[Admins](#for-admins-privacy-settings)**: whoever sets up roles and the Privacy settings.
> - **[Verifying on a dev site](#verifying-on-a-dev-site)**: a manual test script for a bench site.
>
> **Design and decisions**: `docs/superpowers/specs/2026-11-05-ccpa-erasure-requests-design.md`

---

## What this is

When someone asks Northpine to delete their personal information (a CCPA request), the CRM
lets a rep **log** the request, lets Compliance **review and approve** it, and then **erases the person everywhere the CRM holds them in one irreversible step**.

Two deadlines run from the day the request was received:

- **Acknowledge by**: the 10th business day after receipt (Monday to Friday, not counting US federal holidays). Counting starts the day after receipt.
- **Respond by**: 45 calendar days after receipt. Every open request shows "N of 45 days left".

Principles to keep in mind:

- **Leads and deals are never deleted.** Their personal fields are blanked in place, so dashboard numbers, pipeline and revenue do not change.
- **The organization is not the person.** Company records are left as they are.
- **Nobody erases alone.** Reps log. A Compliance member who did not log the request approves.
- **There is no undo.**
- Backups are outside this feature. The existing backup procedure covers a restored backup.

---

## For reps: logging a request

Any CRM user can log a request. You do not erase anything. You record what arrived and hand it to Compliance.

### Log it from a lead, a contact or a deal

1. Open the lead, contact or deal the person is on.
2. Choose **Request erasure** (the button in the page header, or the command palette).
   - On a **deal**, first pick **Who is making the request?** from the deal's contacts. The request starts from that contact.
3. Fill in the form:
   - **How it arrived**: Email, Phone, Web form, Mail or Other.
   - **Date received**: the day it actually arrived. It defaults to today, but enter the real date for a late entry. The deadlines count from this date.
   - **Requester name(s)** as written in the request.
   - **Emails and phones**: any the person wrote from or mentioned. The emails and phones on the lead or contact are added for you.
   - **Original message**: paste the request as it was received.
4. Click **Log request**.

### Log it from a blank form

Use this when the person is not in the CRM under the address they wrote from.

1. Open **Privacy requests** in the sidebar. The sidebar entry is shown to Compliance and Sales Managers. A rep without it logs from a lead, contact or deal, or asks one of them to log the request.
2. Click **Log request** and fill in the same form.
3. The CRM suggests matching records on the next page.

### What happens next

The request is created with a number like `PDR-0001` and the status **Logged**. While it is Logged you can open it and:

- **Confirm or unconfirm matched records.** The CRM suggests leads, contacts and deals whose emails or phones match, plus records linked to a confirmed one (a lead's deals, a contact's deals). **Only confirmed records are erased.** The record you started from is already confirmed.
- **Exclude an identifier** that other people share, such as an office phone line or an `office@` inbox. Each identifier shows how many matches it has. Excluded identifiers are not used to find emails and calls, and are not blocked afterwards.
- Click **Submit to Compliance** when you are happy with the matches.

After you submit, you see only the **status**, **received date**, **acknowledge-by and respond-by dates** and **days left**. This is deliberate. The details are for Compliance.

If the person is a contact on an open deal, the request goes **On Hold** instead (see below), and the deal's owner is told.

### If you own a deal that holds a request

Deal owners get a notification and an email when someone on their open deal has an erasure request. An open deal is one whose status is Open, Ongoing or On Hold (not Won or Lost). Remove the person from the deal's contacts, or close the deal as Won or Lost. When no confirmed person is on an open deal any more, the request returns to **Awaiting Sign-off** on its own.

---

## For Compliance: working a request

You need the **Compliance** role. It is additive: you also keep Sales User or Sales Manager, which is how you open the linked leads, deals and contacts. Sales Managers can see every request but cannot approve, decline or close unless they also hold Compliance.

### Statuses

```
Logged -> Awaiting Sign-off -> Erased -> Closed
              ^   |     \
              |   v      -> Declined -> Closed
            On Hold
```

- **Logged**: the logger is still confirming matches.
- **Awaiting Sign-off**: submitted and ready for review.
- **On Hold**: a confirmed person is a contact on an open deal. Approval is not possible. The 45-day clock and the reminders keep running.
- **Erasing**: a short lock while the erasure job runs. You cannot change the request.
- **Erased**: the job finished. The request waits for the answer to be sent.
- **Declined**: you decided not to erase. A reason is required.
- **Closed**: answered and wiped (see "Closing a request").

### Your list

**Privacy requests** in the sidebar lists open requests, soonest deadline first. Use **Show closed** to include closed ones. You see every request in full.

### Review matches and identifiers

Open the request. You can edit matches and identifiers until it is approved, the same way the logger can.

- **Confirm** each record that is the person. Unconfirm records that only share a value.
- **Exclude** a shared number or inbox. This stops one erasure from wiping colleagues' calls and emails, and from permanently blocking a shared number.
- Only **confirmed, non-excluded** emails and phones drive the sweep of emails, calls and the do-not-contact list.
- Records a request has been removed from while On Hold show a **Removed from open deal** tag.

### Acknowledging

When you send the acknowledgment to the requester, tick **Acknowledgment sent** on the request. The CRM records the date. Until it is ticked, the acknowledgment reminder keeps the deadline in view.

### Contract references

If the person signed a contract or order with Northpine, enter the contract reference(s) in **Contract references** before approving, one per line. At erasure the CRM keeps **only the name and the contract reference** in a separate retained-contract entry. It is deleted automatically after the contract retention period set in Privacy settings. If the period is 0, the entry is kept until counsel sets one.

### Approving

You can approve only when the request is **Awaiting Sign-off**, you hold Compliance, and **you are not the person who logged it**. The server checks this by user.

1. Click **Approve**. The approval screen shows:
   - **Will be removed**: each kind of record, with links and counts.
   - **Will be kept**: the organization, deal values, status and stage, anonymized lead and deal shells, email, call and note records as placeholders, the notes, tasks and files of open deals the person was removed from, and any retained-contract entry.
   - **Needs attention**: open checklist items, and **custom fields on leads, deals or contacts that are not on the personal-fields list**. If one holds personal data, stop, ask an admin to add it to Privacy settings, then come back.
2. Type the request number (for example `PDR-0001`) exactly to confirm.
3. Click **Approve and erase**. This cannot be undone.

If someone was added to an open deal after submission, approving puts the request On Hold instead and tells the deal owner.

Only one approval can ever go through. A second click, or a second Compliance user at the same moment, gets an error.

The erasure runs in the background and is all or nothing. If it fails, the request goes back to **Awaiting Sign-off** and the page shows **The erasure failed** with the error. Fix the cause and approve again.

### What erasure does

| Where | Result |
|---|---|
| Confirmed leads | Personal fields blanked. The name becomes `Erased person PDR-0001`. The lead stays. |
| Confirmed contacts | Personal fields blanked, email and phone rows removed, photo deleted. The contact stays so links hold. |
| Confirmed deals the person is still on | Their row in the deal's contacts is anonymized. The deal's own personal fields are blanked only where they hold the person's values. Values, status and stage are untouched. |
| Addresses linked to the contact | All fields blanked. |
| Emails | **Never deleted.** Subject and content become `Content erased PDR-0001`. Their address in sender, recipients, CC and BCC is replaced with `Erased person PDR-0001`. Other people's addresses on the same email stay. |
| Calls | Record kept. Number replaced, recording link cleared. |
| Notes, tasks, comments | Record kept. Text becomes `Content erased PDR-0001`. Task status, dates and assignee are kept. |
| Files | Deleted. |
| Change history and Frappe's deleted-document copies | Scrubbed. |
| Notifications, email queue, WhatsApp messages and similar | Mentions of the person replaced. |

**Known limitation.** Passing mentions inside other people's records, for example a deal note saying "Marisol prefers Tuesdays", are not searched for or erased. The outcome email tells the requester this.

At the same moment the **do-not-contact** entries are created, so the person is blocked from erasure onwards.

### The checklist

The checklist tracks copies **outside the CRM**. If any erased call had a recording, the job adds **Delete recordings at provider (Twilio)**. You can add items for any other provider that holds a copy.

Delete the copies at the provider, then tick the item. The CRM records who ticked it and when. **A request cannot be closed while any item is open.**

### Declining

On a Logged, Awaiting Sign-off or On Hold request, click **Decline** and give a written reason (for example identity not verifiable, or a legal exemption). You cannot decline a request you logged. A declined request still has to be closed once you have answered.

### Sending the answer

You write and send the answer to the requester yourself. Use the **Erasure outcome** email template. Fill in the bracketed parts before sending:

- **What was erased**, in plain categories, and whether it was also done at external providers.
- **What was kept and why**, such as name and contract reference under the signed-contract exception, or a partial denial and its reason.
- **That a record of the request is kept**: the 24-month log entry and the do-not-contact entry.
- **The known limitation** about passing mentions.

The template is pre-filled with these headings. An edited copy is never overwritten.

### Closing a request

Click **Close request** on an Erased or Declined request. The CRM asks for:

- **Date answered**: required.
- **Outcome**: **Completed**, **Partly completed** or **Denied**.
- **Denial reason**: required when the outcome is Denied.
- A **Declined** request can only close as **Denied**.
- Every checklist item must be ticked.

Keep the requester's email and details until you have replied. Closing wipes them.

Closing also **erases the emails attached to the request**: inbound mail from the requester while the request was open. Their content, subject and the requester's addresses become placeholders, the same as in the erasure.

**What stays after close:**

- A **log entry** with only: date received, request type, how it arrived, date answered, outcome and denial reason. It is deleted automatically **24 months after the date answered** by a daily job.
- The **do-not-contact entries**, which hold only a keyed one-way scrambled form of each erased email and phone. Emails are lowercased and trimmed before scrambling. Phones are normalized, so `(916) 555-0100`, `916.555.0100` and `+19165550100` all count as the same number.
- Any **retained-contract entry**, until its delete-after date.

Everything else is wiped from the request: names, emails, phones, original message, matched-record list and checklist text. Comments on the request and its change history are wiped too.

### The do-not-contact block

- A lead, contact or deal (including its contacts rows) **cannot be created** with an erased email or phone, and an existing record cannot be changed to one. This applies to manual entry, imports, Facebook lead sync, creating a lead from a call log and WhatsApp lead creation. The user sees: "This person asked to be erased under a privacy request. Their details can't be added to the CRM."
- Existing records saved without changing those fields are not blocked.
- Nothing lifts a block. If the person comes back, their old email and phone stay blocked.
- **Incoming email is never rejected**, because that would break mailbox sync. Instead no lead is created from it. While the request is open the email is attached to the request. After close it is attached to nothing and Compliance gets a notification to decide what to do with it. A WhatsApp message from an erased number is saved without a lead, with a notification to Compliance.

### Reminders

A daily job sends each reminder **once per request**, only while the request is not Closed. Each goes out as a CRM notification and as an email. The messages carry the request number and dates only.

| When | Who |
|---|---|
| Acknowledgment not ticked and today is 3 business days before **acknowledge by** (or later) | All Compliance users |
| **Day 30** after receipt | All Compliance users |
| **Day 40** after receipt | The Head of Compliance (all Compliance users if none is set) |

A request logged late gets every reminder already due on the next run, and none twice.

---

## For admins: Privacy settings

Open **Settings -> Privacy**. It is available to Compliance and System Managers.

- **Head of Compliance**: a user. Alerted on day 40 of an unanswered request.
- **Contract retention period (months)**: how long a name and contract reference are kept under the signed-contract exception. **0 keeps them until counsel sets a period.** Counsel sets this value. Do not guess it.
- **Personal fields**: the list of fields that erasure blanks on every matched record, grouped by document type (Lead, Deal, Contact, Deal contacts, Address). It ships pre-filled with names, email, phone and mobile, job title, photo, address, gender and the lead and deal social links. The website field is a company field and is not listed.

### Why custom fields must be added

Erasure only blanks the fields on the list. **A custom field (Settings -> Custom Fields) such as "Personal mobile" is not on the list until someone adds it, so it would be left behind.** When you add a custom field that can hold personal data, add it under Personal fields too. The approval screen flags custom fields that are not on the list, but adding them in advance is safer. The list can only hold fields that exist on the chosen document type.

The settings also hold an automatically generated secret used for the do-not-contact scrambling. It is never shown or returned by the API. Do not change or delete it: entries made with an old secret would stop matching.

### Roles

- Create or assign the **Compliance** role (created on install). Give it to the Privacy team, in addition to Sales User or Sales Manager.
- Only people with Compliance can approve, decline, manage the checklist and close.
- **Compliance** and **Sales Manager** see all requests in full. The logger sees their own request in full only while it is Logged. Nobody else sees requests.

---

## Verifying on a dev site

This is the end-to-end test. It needs a Frappe bench with the CRM app installed. Run it after any change to `crm/privacy/`, `crm/api/erasure.py` or the privacy screens. The automated suites come first.

### Automated suites

```bash
# Backend (on a bench site)
bench --site <test-site> run-tests --app crm

# Frontend
cd frontend
yarn test:run
```

### Setup

Create these users:

- **Tyler**: Sales User. Logs the main request.
- **Dana**: Sales User plus **Compliance** (the approver).
- **Priya**: Sales User plus **Compliance** (a second approver, for the double-approval check).
- **Sam**: Sales Manager, without Compliance.
- **Owen**: Sales User. Owns the deals.
- Optionally a Head of Compliance user, set in Settings -> Privacy.

Add a custom field **Personal mobile** to CRM Lead (Settings -> Custom Fields). Do **not** add it to Personal fields yet.

Create the data for **Marisol Vega** (`marisol.vega@sierrafoothills.example`, phone `(916) 555-0100`) in the organization Sierra Foothills Dental Group:

- A **lead** for Marisol, with Personal mobile set to `916-555-0199`. Attach a file to it (for example `proposal.pdf`). Add a note and a task. Edit the lead's phone once, so that change history holds an old value.
- A **duplicate lead** with Marisol's email, then delete it, so a Deleted Document copy exists.
- A **contact** for Marisol, with an **Address** linked to it.
- Three **deals**, all owned by Owen and each with a value:
  - **Deal A** in **Negotiation** (an open status), listing Marisol's contact. Add a note and a file to it.
  - **Deal B** in **Won**, with Marisol's contact as the primary contact (so the deal's own email, mobile and phone hold Marisol's values). Add a note and a file.
  - **Deal C** in **Won**, where **Chris Lee** (another contact, with their own email, mobile and phone) is the primary contact and Marisol's contact is a second, non-primary contact.
- Several **emails** with Marisol's address, including one with a colleague CC'd, for example `"Marisol Vega" <Marisol.Vega@sierrafoothills.example>, bob@sierrafoothills.example`.
- A **call log** with a recording.
- On Deal A, a note that mentions "Marisol prefers Tuesdays". This is the known limitation: it is expected to survive.

### Script

1. **Record the dashboard.** Open the dashboard and write down the lead count, the deal count, the won and ongoing deal values, and the breakdowns by status and source.
2. **Log from the lead.** As Tyler, open Marisol's lead, click **Request erasure**, set the received date to a recent date, add Marisol's email and phone, and click **Log request**.
   - Expect: a new `PDR-` number, status **Logged**, the lead as a confirmed match, and Marisol's contact and the deals suggested as matches.
3. **Confirm matches.** Confirm the contact and all three deals. Check that the email and the phone each show a match count.
4. **Submit.** Click **Submit to Compliance**.
   - Expect: status **On Hold**, because Marisol's contact is on Deal A, which is open. Owen gets a notification and an email about Deal A.
   - Expect: Tyler now sees only status, dates and days left.
5. **Try to approve while On Hold** as Dana. Expect that **Approve** is not offered, and the API refuses it.
6. **Resolve the hold.** As Owen, remove Marisol's contact from Deal A's contacts and save.
   - Expect: the request returns to **Awaiting Sign-off**, and the match on Deal A shows **Removed from open deal**.
7. **Check who cannot approve.**
   - As Tyler (the logger) and as Sam (Sales Manager without Compliance): **Approve** is not offered, and calling the endpoint is refused.
   - As Dana: it is offered.
8. **A logger with Compliance cannot approve.** As Dana, log a separate request from any unrelated lead and submit it.
   - Expect: **Approve** is not offered to Dana on that request, and calling `crm.api.erasure.approve` as Dana is refused ("Only a Compliance user who did not log this request can approve it."). **Decline** is refused too.
   - As Priya: **Approve** is offered. Decline this request as Priya with a reason, then close it as **Denied**, so it does not stay open.
9. **Open the approval screen** as Dana, on Marisol's request.
   - Expect: **Will be removed** lists the lead, the contact, Deals B and C, the emails and calls, notes, tasks and files. **Will be kept** lists the organization, deal values and Deal A's own notes, tasks and files. **Needs attention** flags the custom field **Personal mobile**.
10. **Add the custom field.** In Settings -> Privacy, add **CRM Lead -> Personal mobile** and save. Reopen the approval screen and confirm the flag is gone.
11. **Approve.** As Dana, type the request number wrongly (expect an error), then correctly, and click **Approve and erase**.
    - Expect: status **Erasing**, then **Erased**. Have Priya call approve right after: expect an error, and only one erasure job in the background job list.
12. **Check the erased data.**
    - Lead: name is `Erased person PDR-xxxx`; email, phone and Personal mobile are blank. The lead still exists. Its note and task text is `Content erased PDR-xxxx`, with the task's status, dates and assignee kept. The attached file is gone.
    - Contact: names are the placeholder, and the email and phone rows are gone. The Address linked to the contact has every field blank.
    - Deal B (Won, Marisol primary): the contacts row is anonymized (name is the placeholder, email and phone blank, the contact link kept). The deal's own name, email, mobile and phone fields are blank. Its notes are erased and its file is gone. Its value, status and stage are unchanged.
    - Deal C (Won, Chris Lee primary): Marisol's row is anonymized, but **Chris Lee's email, mobile and phone on the deal are untouched**.
    - Deal A (Marisol's contact was removed): its own notes, tasks and files are still there, including the "Marisol prefers Tuesdays" note.
    - Emails: content is `Content erased PDR-xxxx`; Marisol's address is replaced with `Erased person PDR-xxxx`, in any case or display-name form; `bob@sierrafoothills.example` is unchanged on the email with the CC.
    - Call log: number replaced, recording link cleared.
13. **Check the checklist.** Expect **Delete recordings at provider (Twilio)** on the request.
14. **Check the dashboard.** Compare with step 1. **Every number and breakdown must be identical.**
15. **Sweep for what is left.** Take a backup (`bench --site <test-site> backup`) and search the SQL file, case-insensitively, for the email and every phone form:
    ```bash
    grep -i -E "marisol\.vega@sierrafoothills|555[-. )]*0100|555[-. ]*0199" <backup>.sql
    ```
    Then look in the Desk lists **Version** and **Deleted Document** (filter on the document types Lead, Deal, Contact and Communication) and open the duplicate lead's copy.
    - Expect: no hits in the backup. The do-not-contact entries hold only scrambled hashes, so they do not match. The Version rows have placeholders where the email, phone and name were, and the Deleted Document copy of the duplicate lead is scrubbed or gone. The note on Deal A may still say "Marisol", which is the known limitation. Any other hit is a bug.
16. **Check the block.** Try to create a new lead with Marisol's email, then another with `916.555.0100` as the phone, then a deal with a contact row holding either value.
    - Expect: each is refused with "This person asked to be erased under a privacy request. Their details can't be added to the CRM." Changing an existing record's email to the erased one is refused too. A record saved without touching those fields still saves.
17. **Send an email from Marisol's address** to a connected mailbox, while the request is Erased and not yet closed.
    - Expect: no lead is created and the email is attached to the request.
18. **Try to close early.** As Dana, click **Close request**, enter a date answered and the outcome Completed.
    - Expect: refused, because the Twilio item is open.
19. **Tick the checklist item**, then close with **Completed**.
    - Expect: the request now holds only the log fields (received, type, how it arrived, answered, outcome and denial reason). Names, emails, phones, message, matches and checklist text are gone. **Kept until** shows a date 24 months after the answered date.
    - Expect: the email from step 17, still attached to the request, now has content `Content erased PDR-xxxx` and Marisol's address replaced. Closing erases emails attached to the request.
20. **Check the block after close.** Repeat step 16. It must still be refused. Send another email from Marisol's address: expect no lead, no link, and a notification to Compliance. Repeat the sweep from step 15 and expect no new hits.
21. **Reminders.** Log another request (as Tyler) with a received date 41 days ago and run the scheduler (`bench --site <test-site> execute crm.privacy.reminders.send_due_reminders`).
    - Expect: the acknowledgment, day-30 and day-40 reminders each go out once (notification and email), the day-40 one to the Head of Compliance. Run it again and expect nothing new.
22. **Decline path.** Log another request as Tyler, submit it, and decline it as Dana with a reason. Try to close it as **Completed**: refused. Close it as **Denied** with a reason: allowed.

Record any step that does not behave as written and treat it as a bug.

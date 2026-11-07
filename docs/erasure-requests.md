# Personal data erasure requests (CCPA)

How the CRM logs, approves and carries out a request to delete a person's personal data. The design of record is
[design/2026-11-05-ccpa-erasure-requests-design.md](./design/2026-11-05-ccpa-erasure-requests-design.md); this page
is the operator and developer summary. Where they differ, the design wins.

Erasure is **irreversible**, needs **two people**, and **never moves a dashboard number**: leads and deals are
anonymized in place, never deleted.

## Who does what

| Person | Can |
|---|---|
| Any CRM user (rep) | Log a request from a lead, contact or deal page, or from a blank form on the requests list. Confirm matches and identifiers while the request is *Logged*, then submit it. After submitting, sees only status and due dates. |
| Sales Manager | Log, and see every request in full. Cannot approve. |
| **Compliance** (role) | See every request, confirm or exclude matches and identifiers, enter contract references, approve or decline, manage the checklist, record the acknowledgment, close. Cannot approve a request they logged. |
| Head of Compliance (a setting) | Receives the day-40 alert. Falls back to all Compliance users when unset or disabled. |
| System Manager / administrator | Grants and removes the Compliance role (Settings, Privacy). Cannot grant it to themselves. Is **not** Compliance unless given the role explicitly: an `Administrator` login holds every role in `frappe.get_roles`, so the approval check reads the explicit `Has Role` row instead. |

**Compliance is granted only on the Privacy page** (Settings, Privacy, Members), where each grant and revoke leaves an
audit comment. Frappe's setup wizard gives its first user every role that exists, Compliance included, so a
`setup_wizard_complete` hook (`crm.privacy.compliance_members.revoke_unaudited_grants`) takes the role back from any
holder with no grant comment and leaves one comment with the count, no names. The first System Manager then grants
Compliance to the right people on the Privacy page. Sites that already exist are not touched: the hook runs only at
the end of the wizard.

A user who holds only Compliance sees one sidebar entry, "Erasure requests", and the SPA skips every request that needs
a sales role (FCRM Settings, availability statuses).

## Lifecycle

```
Logged -> Awaiting sign-off -> Erased -> Closed
              ^   |     \-> Declined -> Closed
              On Hold
```

1. **Logged.** The rep enters the requester's names, emails, phones, the message, how and when it arrived. The CRM
   suggests matching leads, contacts and deals (by email and phone, plus records linked to a confirmed match). The
   rep confirms which are the person. The record the request started from is pre-confirmed. Identifiers can be
   excluded (a shared office line) so one erasure cannot wipe colleagues' emails and calls.
2. **Submit.** If a confirmed person is on an open deal (status type Open, Ongoing or On Hold), the request goes
   **On Hold**: each deal owner is notified to remove her or close the deal. The 45-day clock keeps running. It returns to
   *Awaiting sign-off* when no open deal lists her any more (checked on deal save, daily, and by "Re-check hold").
3. **Approval.** Compliance opens the preview: *Will be removed* (counts and links per kind), *Will be kept*, *Needs
   attention* (open checklist items, custom fields not on the personal fields list, identifiers that also match records
   outside the confirmed ones). The approver types the request number. Server checks: explicit Compliance role, not the
   logger, not On Hold, retention period set when contract references exist.
4. **Erasure job.** One background job, all or nothing. It re-checks the hold, the approver and a hash of the approved
   plan, so what runs is what was approved; a changed plan sends Compliance back to the preview. While it is Queued or
   Running the request is frozen. A failure rolls everything back, leaves the request in *Awaiting sign-off* with the error
   shown, and logs only the request number and the exception class. A job that never finishes is failed by an hourly reaper.
5. **Erased.** The do-not-contact entries exist from this moment. The checklist may hold items added by the job.
6. **Close.** Compliance records the date answered (between received and today), the outcome (Completed, Partly
   completed, Denied) and a reason for Denied and Partly completed. Every checklist item must be done. A Declined
   request closes as Denied.

Declining needs a written reason and is possible before the erasure.

**If the plan changed after approval.** The hash covers everything the job would touch, history and traces included
(versions, route history, notifications, queued mail). On a busy queue, an edit to one of her records between the
click and the job (a status change writes a Version) makes the job refuse with "Plan changed since approval". Nothing
is erased, the request stays *Awaiting sign-off*, and Compliance reviews the preview and approves again. This is
deliberate (RT-1): what runs is exactly what was approved, and a stricter check is safer than a looser one.

## Deadlines and reminders

- **Respond by** = received + 45 calendar days. Open requests show "N of 45 days left" and the list sorts by it.
- **Acknowledge by** = the 10th business day after receipt (Mon-Fri, excluding US federal holidays computed from their
  statutory rules, observed dates included). 26 Oct 2026 gives 9 Nov 2026.
- Reminders, each sent once as a CRM notification and an email, only while the request is not Closed:
  acknowledgment not sent 3 business days before *acknowledge by* (all Compliance), day 30 (all Compliance), day 40
  (Head of Compliance). Reminders already due when a request is logged late go out on the next run.

**The scheduler must be running.** The daily jobs are `crm.privacy.reminders.send_due_reminders`,
`crm.privacy.on_hold.recheck_all_on_hold` and `crm.privacy.retention.purge_expired`; the hourly one is
`crm.privacy.erasure.recovery.reap_stale_jobs`. The erasure itself needs a background worker. Without them reminders
never go out, On Hold requests do not release on their own, stuck jobs are not recovered and expired log entries stay.

## What is erased and what is kept

| Where | Result |
|---|---|
| Confirmed lead | Personal fields blanked; name becomes `Erased person PDR-0001`. Record stays. |
| Deals she is still on (Won/Lost) | Her contacts row anonymized; the deal's personal fields blanked only where they hold her values; its notes, tasks, comments, emails, calls and files wiped. Values, status, stage untouched. |
| Open deals she was removed from | Only emails and calls with her address or number are wiped. Other notes, tasks, comments, files stay. |
| Contact, address | Names to placeholder, email and phone rows removed, photo deleted; the docname is renamed to the placeholder so every link follows (an address shared with someone else only loses her link). |
| Emails, calls, notes, tasks, comments (every comment type) | Records kept, text replaced by `Content erased PDR-0001`, her addresses and numbers by `Erased person PDR-0001`, recordings cleared. |
| Files | Row and bytes deleted; the bytes go only after the commit. |
| Change history, deleted-document copies | Her values scrubbed; non-personal changes kept. |
| Notifications, queued mail, WhatsApp, event participants, failed lead-sync logs, enrichment changes, route history, saved filters, global search | Scrubbed or removed. A failed lead-sync log is one rejected lead, so every text in it goes. |
| Kept | Organizations, deal values, status, stage, owner, source, dates, the anonymized shells, and a **retained-contract** entry (her name and the contract reference) when Compliance gave references, deleted automatically after the contract retention period. |

At close the request's own names, emails, phones, message, matches, checklist and the emails and files attached to it
are wiped. What remains is a **log entry** (dates, type, channel, outcome, denial reason) deleted 24 months later.

## Do not contact

Each erased email and phone is kept only as a keyed hash (secret in Privacy settings; emails lowercased, phones in
E.164 first). Nothing lifts a block. A lead, contact or deal, including its contacts rows, whose email or phone matches is
refused on create and on a change to a matching value (manual entry, import, Facebook sync, call log, WhatsApp). Existing
records saved without changing those fields are not blocked. Incoming email is never rejected: no lead is created, it is
attached to the open request, or after close to nothing, with Compliance notified.

### While the do-not-contact secret is missing

Entries exist but the secret is gone (a restore with another `encryption_key`). Nothing can be checked, so no new
block is created and nothing is regenerated: a new secret would orphan every block. Restore it from a backup (the
`__Auth` row of CRM Privacy Settings together with the site's `encryption_key`). Meanwhile each path fails the way that
loses the least:

- **Manual saves** (lead, deal, contact) fail closed with "Privacy settings are incomplete".
- **Facebook sync**: the lead is not imported and not consumed. It leaves a *Failed Lead Sync Log* of type Failure
  that holds **only the Meta lead id** and a fixed note, no name, email or phone, so nothing about a person who may
  have asked to be erased is kept. After the secret is restored, "Retry Sync" on that log fetches the lead from Meta
  by its id and imports it (or skips it, if she is on the list). While the secret is still missing a retry raises the
  same message and the log stays Failure. The sync re-reads the last few minutes, so one lead gets one log.
- **WhatsApp**: the message is kept and no lead is created from it (it stays unlinked).
- **Inbound email**: never rejected, no lead is created, and Compliance is told.
- Compliance gets one notice a day while it lasts, and each failure writes an Error Log with the context and class
  name only. "Restore defaults" (and the install patch) no longer raise on such a site.

## Outcome email

Compliance sends the answer. The "Erasure outcome" template says what was erased, what was kept and why, that a log
entry and a do-not-contact entry remain, and the limitation below. Fill every `[COMPLIANCE: ...]` marker first.

## Adding personal fields

Settings, Privacy, personal fields table: one (doctype, field) row per field that identifies the person, for CRM Lead,
CRM Deal, Contact, Contact Email, Contact Phone, CRM Contacts and Address. It ships pre-filled; admins add rows (for
example a custom "Personal mobile" field). Each change is audited with a comment. The approval preview lists fields on
those doctypes that are **not** on the list, so a gap is visible before anyone approves. Placing a field on the list
changes the next approval's plan, not requests already approved.

## Known limitations

- **Passing mentions** of the person inside other people's records (a note saying "Marisol prefers Tuesdays") are not
  searched for or erased. The outcome email says so.
- **Backups** are handled by the existing backup procedure for any restored backup.
- **External providers** (for example Twilio recordings) are tracked by checklist items that block closing, not deleted
  by the CRM. **Data Import source files** that may hold her row get an automatic checklist item; they are not parsed.
- **Company data** and the ERPNext integration are out of scope. Requests to know, correct or opt out are a separate project.
- The mobile layout has no erasure pages.
- **Approval on large sites is slow.** The preview and Approve build the plan inside the web request, and the email and
  deleted-document searches (`LIKE '%…%'`) can't use an index. Measured on a site with 300k Communications, 300k Versions
  and 30k Deleted Documents, the preview took about 15 s and Approve about 7.5 s. The time grows with the number of rows:
  about 50 s at 1M Communications, still under Frappe's default 120 s web timeout. It is slow, never unsafe, because the
  erasure job rebuilds the plan and checks it against what was approved. Planned follow-up: build the preview in a
  background job, store it with its hash on the request, and have Approve use the stored hash.
- **A held Facebook lead for a person already on the list** is dropped when it is retried, and its sync log shows
  "Synced" even though no lead was created. The log holds only the Meta lead id.

## Where the code is

| Part | Location |
|---|---|
| Logic | `crm/privacy/` (`erasure/` holds the plan, preview and scrubbers; `request_*.py` lifecycle; `do_not_contact.py`, `blocking.py`, `inbound_email.py`) |
| Whitelisted API | `crm/api/erasure_requests.py` (lifecycle), `erasure_review.py` (Compliance), `erasure_settings.py`, `erasure_inbound.py` |
| Doctypes | `CRM Erasure Request` (+ identifier, match, checklist item, contract reference children), `CRM Do Not Contact`, `CRM Retained Contract`, `CRM Privacy Settings` (+ `CRM Personal Field`) |
| Frontend | `frontend/src/pages/ErasureRequest(s).vue`, `components/ErasureRequests/`, `components/Settings/PrivacySettings.vue` |
| Tests | `crm/privacy/tests/` and `frontend/tests/unit/erasure*.test.js` |

Privacy code logs through `crm.privacy.error_log.log_privacy_error` (a title and a class name, neutral metadata), never
`frappe.log_error`: that one stores the web request's form data, which on a deal save or a webhook holds the person's
email, phone or message, and reports the live exception to Sentry. `request_visibility.INTERNAL_FIELDS`
(`approved_plan_hash`, `pending_file_deletions`) sit at permlevel 1 that no role can read, so `frappe.client.get` returns
them as empty; the server reads and writes them with `ignore_permissions`.

Two end-to-end tests guard the anti-goals: `test_dashboard_invariance.py` (every dashboard number, as administrator and
as the deal owner, identical before and after the whole lifecycle) and `test_erasure_leak_sweep.py` (every text column of
every table searched for her emails, phones and name after the erasure and after the close). A failing sweep means data
survives somewhere: fix the scrubber, not the test.

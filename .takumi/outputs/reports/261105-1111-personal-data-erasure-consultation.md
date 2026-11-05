# Consultation — Personal Data Erasure (CCPA) in Frappe CRM

Status: **approved** (2026-11-05, Path A) · Lens: CTO · Date: 2026-11-05
Sources: `03-slack-thread.txt`, `04-emails.txt`, `crm/fcrm/doctype/*`, `crm/api/dashboard.py`, `crm/hooks.py`

## 1. Commission

Let the CRM erase one person's personal data on request: the rep who received the request logs it
there, and a second person approves and runs the erasure.

First case: Marisol Vega (CA resident, ex-Sierra Foothills Dental). Request received 2026-10-26.
Acknowledgement due Nov 9 (Dana sends it). Response due Dec 10.

### Hard requirements (stated)
| # | Requirement | Source |
|---|---|---|
| R1 | The rep logs the request from the person's record, on the person's behalf | Tyler/Priya 09:20 |
| R2 | Scope is the **person**; organization records stay | Dana 09:24 |
| R3 | A rep never erases alone; the approval comes from a **new Privacy Officer role** | Dana/Priya 09:27, user |
| R4 | Pipeline and revenue numbers **must not move** | Finance via Priya 09:31 |
| R5 | Backups are out of scope | Dana 09:40 |
| R6 | Track the deadlines: acknowledge within 10 business days, respond within 45 calendar days | Dana email |

### Decisions made in this consultation (user)
- **Discovery:** search the emails, calls, notes and tasks on her lead and both deals, plus every record that matches any of her emails or phone numbers. The requester reviews the matches and removes the ones that are clearly someone else before submitting.
- **No deletion of activity:** content is replaced with `Content erased <REQ-no>` and the records stay, so counts and reports don't move.
- **Out of scope:** mentions of her inside other people's records. These are listed as a known limitation in the outcome.
- **On Hold:** while she is on an open deal, the request is On Hold until the deal owner removes her or closes the deal. The deadline keeps running.
- **Confirmation:** the approver sees the final preview and types the request number to confirm.
- **Timeline:** build in November, pilot with the Privacy team in December, live for all reps by **2027-01-15**. If the feature isn't live in time, the Privacy team handles Marisol manually before Dec 10, and the manual steps must also cover change history and deleted-record copies. No one-off script.

### Out of scope
Backups · company records · mentions of her in other people's records · the slow kanban/list views (09:33, unrelated, so file it as a separate ticket).

## 2. What the codebase says (evidence)

| Finding | Evidence | Consequence |
|---|---|---|
| Lead rows feed the dashboard | `dashboard.py`: `get_total_leads`, `get_funnel_conversion`, `get_leads_by_source`, `get_average_time_to_close_a_lead` | Lead **must be anonymized in place, never deleted** (R4) |
| Deal copies the person fields | `crm_deal.json`: `email, mobile_no, phone, first_name, last_name, lead_name, salutation, gender, job_title, contact` + `contacts` (CRM Contacts: `full_name, email, mobile_no, phone`) | The scrub has to cover the Deal's own fields as well as the linked Contact |
| Change history keeps the old values | `track_changes: 1` on CRM Lead, CRM Deal, FCRM Note | Existing `Version` rows hold her data, and **the scrub itself writes a new Version with the old values** unless that is suppressed |
| A deletion leaves a copy | Frappe `delete_doc` writes to `Deleted Document` unless `delete_permanently=True` | Previously deleted notes/contacts about her may still exist and have to be found and purged |
| Reps can delete today | `Sales User` has `delete` on Lead and Deal | A rep can delete a record while a request is pending. Block delete on records linked to an open request |
| Calls point outside the CRM | `CRM Call Log.recording_url`, `from`, `to` | Recordings at Twilio/Exotel are **outside the CRM**, so they go on the known-limitations list |
| Frappe's own GDPR hook is unused | `crm/hooks.py:412` `# user_data_fields` (commented out) | Basis of Path B below |

### Where her data lives (the "erasure registry" — the core artifact of this feature)
| Doctype | Action |
|---|---|
| CRM Lead | Scrub person fields (name, email, phones, job title, gender, salutation, image, social links). Keep status, source, owner, territory, org, values, dates |
| CRM Deal (both) | Scrub the person fields and `contacts` rows. Keep status, value, probability, dates, owner, org |
| Contact (+ Contact Email/Phone, Address via Dynamic Link) | Anonymize in place so the deal links stay valid. Remove the email/phone child rows |
| Communication | Replace subject and content. Scrub `sender`, `recipients`, `cc`, `bcc` |
| FCRM Note, CRM Task, Comment | Replace content and title |
| CRM Call Log | Clear `from`/`to` (her number) and `recording_url`. Replace the linked note |
| File (email attachments, lead image) | **Delete permanently.** Files aren't counted in any report |
| CRM Notification | Scrub `message` / `notification_text` |
| Email Queue (+ Recipient) | Scrub or purge the outgoing copies |
| Version | Lead/Contact: purge. Deal: drop person-field entries only, and keep the status/value audit |
| Deleted Document | Purge rows whose data matches her identifiers |
| Global search index | Re-index or remove the scrubbed docs |

Matching: exact, case-insensitive email, and **normalized** phone (digits only, with country code).
Matching on name alone is never automatic.

## 3. Paths examined

### Path A — Custom `CRM Erasure Request` doctype + registry-driven erasure service ✅ Recommended
The request doctype holds the status, dates, matched-items preview, approver and outcome. A Python
service runs over the declarative registry above: discover → preview → execute, in one DB
transaction, with the file deletions last.
- **Pro:** fits every decision above (On Hold, preview, typed confirmation, Privacy Officer). The registry is one place to add a new data source (e.g. WhatsApp) and is unit-testable per doctype. Logging from the person's record works in the Vue UI.
- **Con:** we own every hidden copy (Version, Deleted Document, search index, Email Queue), so a miss is our bug. This is the largest build of the three paths.

### Path B — Extend Frappe's built-in `Personal Data Deletion Request` (`user_data_fields` hook)
- **Pro:** core anonymization plumbing that already exists.
- **Con:** it is built for a **website user deleting their own account** (email verification sent to the subject, matched by email only, no second approver, no preview, no On Hold, no phone matching). We would fight its workflow on every requirement. *INFERRED: based on Frappe's standard GDPR module; verify the version-specific behavior before rejecting it outright.*

### Path C — Hard delete or "hide" the person — ❌ Rejected
Hard delete breaks R4 (dashboard counts move, and deal deletion moves pipeline). Hiding is not erasure under the CCPA.

## 4. Agreed direction (approved)
Path A, with these design points:
1. **States:** Draft → Pending Approval → On Hold → Approved/Executed → Closed, plus Rejected. On Hold is re-checked automatically when the blocking deal changes, and on an approve attempt.
2. **Two people, enforced on the server:** `approver != requester`, and the approver must have the Privacy Officer role. Enforce this in Python, not only in the UI.
3. **Re-discover at execution time.** The match list drifts while the request is On Hold (she may reply, reps log calls). The approver sees items that are *new since logging* flagged separately and can exclude them.
4. **Dates:** `received_on` (the date the rep got the request, not the logging date), `ack_due` (+10 business days, using the CRM Holiday List), `response_due` (+45 calendar days), `acknowledged_on`. Highlight overdue requests and requests close to their due date.
5. **The outcome record is free of PII:** counts per doctype, doc names, and the known-limitations list (other people's mentions, call recordings at the provider, rep mailboxes outside the CRM, backups).
6. **Block deletes** on any Lead/Deal/Contact linked to an open request.
7. **Scrub without leaving traces:** write via `db.set_value`/`db_set` with `update_modified` handled, no new Version rows, and purge the existing Version / Deleted Document rows per the registry.

## 5. What to watch
- **Retaining the request itself.** CCPA rules (11 CCR §7101) require keeping records of requests for **24 months**. The request record holds her name and email, so Dana must decide what stays on it after execution (e.g. masked email + REQ number). *INFERRED, needs Dana's confirmation.*
- **The On Hold exit can still move the pipeline.** If the owner closes the Negotiation deal as Lost, the pipeline changes. That's a business action, not the erasure, but tell Finance/Marcus in advance.
- **The manual fallback for Marisol needs an admin.** Purging Version, Deleted Document and the search index takes System Manager or console access, so the Privacy team can't do it alone. Write a manual runbook built from the same registry table, before Dec 1.
- **Phone normalization** is the weakest link in matching. Test it with real formats from the data.
- **Partial failure:** DB work in one transaction, file deletions only after the commit. Execution can be re-run safely (it skips items that are already scrubbed).
- **Safety-critical area** (personal data + data mutation). The full test group covers the registry per doctype, the permission rules (self-approval rejected, non-Privacy-Officer rejected), the On Hold transitions, and "dashboard numbers identical before and after" as an integration test.

## 6. Success measures
- After execution, a DB-wide search for her emails and phones (all tables, including Version, Deleted Document, the search index and Email Queue) returns **zero rows** outside the request record's retained fields.
- All dashboard endpoints in `dashboard.py` return identical values before and after.
- A request can't be executed by the person who logged it, or by anyone without Privacy Officer.
- Privacy team pilot in December completed. All reps live by 2027-01-15.

## 7. Open items (unresolved)
- What the request record retains after execution (Dana).
- Where the Privacy Officer works: a CRM UI page (recommended, since the logging dialog lives there anyway) or Frappe desk.
- Whether Sales User should lose global delete on Lead/Deal (Priya; a separate decision from this feature).
- Verify Path B's actual behavior in the installed Frappe version before closing it.

## 8. Next
On approval → `/tkm:create-plan` with this report as input.

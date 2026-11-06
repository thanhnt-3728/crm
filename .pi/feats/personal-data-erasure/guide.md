# Personal data erasure (CCPA)

> **Who is this for?** Sales reps who log an erasure request, and Privacy Officers who approve it.
> **Contract**: [SPEC.md](../../SPEC.md#personal-data-erasure)
> **Why it works this way**: [ARCHIVE.md](../../ARCHIVE.md#ccpa-personal-data-erasure)
> **Manual fallback** (System Manager, when the CRM flow cannot be used): [docs/ccpa-manual-erasure-runbook.md](../../../docs/ccpa-manual-erasure-runbook.md)

A person can ask us to delete her personal data. We must acknowledge her within 10 business days and answer within 45 calendar days of receiving the request. The CRM does the work in two steps by two different people: a rep logs the request, a Privacy Officer approves it. Her Lead, Deal and Contact are anonymized in place. Emails, comments, calls, notes, tasks and WhatsApp messages stay as rows with their content replaced by `Content erased <request number>`, so counts and dashboards do not change. Her files are deleted permanently.

**Never paste her email or phone into a ticket or chat.** Use the request number (for example `CRM-ERQ-2026-00001`).

---

## For reps: log a request

1. Open her **Lead**, **Deal** or **Contact**.
2. Click **Log erasure request** (shown to System Manager and Sales User; Sales Manager is read-only). On a Lead or Deal it is an icon button with the tooltip "Log erasure request"; on a Contact it is a labelled button. It is also in the command palette.
3. In the dialog **Log erasure request**, fill in:
   - **Name of the person**
   - **Request received on** (not a future date)
   - **Email addresses (one per line)** and **Phone numbers (one per line)**, prefilled from the record. At least one must be on this record.
4. Click **Find matches**. The dialog shows the deadlines ("Acknowledge by ..., respond by ...") and every record found for her, grouped by type, plus the copies that will also be removed ("Also removed from system copies").
5. Review the matches. If a record belongs to someone else (for example a shared mailbox), tick **Exclude** on it. A record reachable only through an excluded one shows **Excluded with its parent** and follows it.
6. Click **Submit for approval**.

Closing the window before that keeps the request as a Draft in **Erasure Requests**. If a Draft already exists for the record, the dialog offers **Open it**.

If one of her deals is still open, the request goes **On Hold** straight away ("Request logged and put on hold: an open deal is linked to this person"). It returns to Pending Approval by itself once those deals are Won or Lost. The deadlines keep running meanwhile.

Acknowledge her yourself within 10 business days, then record the date on the request page (**Acknowledged on**, **Save**).

You can follow a request under **Erasure Requests** in the sidebar. You cannot approve your own request.

---

## For Privacy Officers: approve, reject, retry, close

You need the **Privacy Officer** role plus a CRM role. Open **Erasure Requests** and click a request in **Pending Approval**.

### Approve

1. Click **Approve**. The dialog **Approve erasure** loads a fresh preview.
2. Read the warning: approving permanently erases or anonymizes the records and cannot be undone. Tick **Exclude** on any record that must be kept.
3. If records appeared after the request was logged, a notice says "N new record(s) found since the request was logged" and lists them first. Tick **I reviewed the N new records**.
4. Type the request number in **Type <request number> to confirm**.
5. Click **Approve and erase**. The erasure runs in the background; the page refreshes until it finishes.

If the matches changed while the dialog was open you get "Matches changed, reload the preview": the preview reloads and you confirm again.

You cannot approve a request you logged or own. If an open deal appeared in the meantime, the request returns to On Hold instead.

### Reject

Click **Reject**, give a **Reason (required)** and click **Reject** again. Possible while the request is Draft, Pending Approval or On Hold. Rejecting masks the stored identifiers and drops her name, as Close does.

### Retry a failed erasure

If the job fails, the request stays **Approved** and the page shows "Last error: ...". Fix the cause (the message names the doctype or table, never her data), then click **Retry**. Retry also appears when an Approved request has not finished within 25 minutes ("Execution has not finished. Retry."). If files were not deleted from disk, the Outcome lists pending files; a System Manager retries with `bench --site <site> execute crm.erasure.post_commit.finish_files --kwargs "{'name': '<REQ>'}"`. Nothing is half-erased: a failed job is rolled back.

### Close

When the request is **Executed**, read the **Outcome** and the known limitations on the page, answer the person, then click **Close**. Closing masks the stored email and phone and drops her name, keeping the request number and dates for record keeping.

---

## States at a glance

Draft, Pending Approval, On Hold, Approved, Executed, Closed, Rejected. The legal moves and who makes them are in [SPEC.md](../../SPEC.md#personal-data-erasure). While a request is Draft, Pending Approval, On Hold or Approved, her Lead, Deal and Contact cannot be deleted or renamed.

## Admin setup

- The role **Privacy Officer** is created on install and by migration; assign it to the Privacy team.
- **FCRM Settings > Privacy Requests > Erasure Request Holiday List**: pick a CRM Holiday List so the 10-business-day count skips those days. Empty means weekends only.

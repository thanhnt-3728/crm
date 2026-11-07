# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The "Erasure outcome" email template (design 5.10; phase 06).

Compliance writes and sends the answer to the requester. The template holds the four things the design says it
must say; every request-specific part is a `[COMPLIANCE: ...]` marker to fill in before sending. It is created only
when missing, so an administrator's edits are never overwritten.
"""

import frappe

NAME = "Erasure outcome"
REFERENCE_DOCTYPE = "CRM Erasure Request"
SUBJECT = "Your request to erase your personal data ({{ name }})"
RESPONSE = """<p>Hello [COMPLIANCE: the requester's name],</p>
<p>We have finished your request to erase your personal data (reference {{ name }}). This is what we did.</p>

<h4>What was erased</h4>
<p>[COMPLIANCE: delete the lines that do not apply]</p>
<ul>
<li>Contact details: name, email addresses, phone numbers and address.</li>
<li>Lead and deal records: they remain only as anonymized shells without any personal details.</li>
<li>Emails and calls, including call recordings.</li>
<li>Notes, tasks and comments.</li>
<li>Files and attachments.</li>
</ul>
<p>Copies held by external providers: [COMPLIANCE: for each provider (for example Twilio call recordings), say whether the copy was deleted, or when it will be].</p>

<h4>What we kept, and why</h4>
<p>[COMPLIANCE: write "Nothing", or list each item kept with its reason. Under the signed contract or order exception we keep only your name and the contract reference [CONTRACT REFERENCE] for [RETENTION PERIOD]. If we could not do part of the request, say which part and why.]</p>

<h4>The record we keep of your request</h4>
<p>We keep a short log entry of your request: the date we received it, how it arrived, the date we answered you, the outcome and, if any part was denied, the reason. We delete this entry automatically after 24 months.</p>
<p>We also keep a do-not-contact entry. It holds only a one-way scrambled form of your email address and phone number, so that your details cannot be entered into our system again. It cannot be turned back into your details.</p>

<h4>One limitation</h4>
<p>We did not search for, or erase, passing mentions of you inside other people's records (for example a note on someone else's deal).</p>

<p>[COMPLIANCE: your name and how to reach the Privacy team]</p>
"""


def install_outcome_template() -> None:
	"""Create the template if it is missing. Safe to run again."""
	if frappe.db.exists("Email Template", NAME):
		return
	template = frappe.new_doc("Email Template")
	template.update({"subject": SUBJECT, "response": RESPONSE, "reference_doctype": REFERENCE_DOCTYPE})
	if template.meta.has_field(
		"enabled"
	):  # a CRM custom field: only enabled templates are offered in the CRM
		template.enabled = 1
	template.name = NAME
	template.insert(ignore_permissions=True)

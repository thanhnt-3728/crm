"""Install/migrate hooks for the privacy (erasure request) module."""

import frappe

from crm.privacy.identifiers import ensure_secret
from crm.privacy.rules import DEFAULT_PERSONAL_FIELDS

COMPLIANCE_ROLE = "Compliance"
OUTCOME_TEMPLATE = "Erasure outcome"
OUTCOME_SUBJECT = "Your request to delete your personal information"
OUTCOME_HTML = """<p>Dear [name],</p>
<p>On [date received] you asked Northpine to delete the personal information we hold about you. We have completed our review.</p>
<p><strong>What we erased.</strong> We erased your contact details, your lead and deal records, emails, call records, notes and files from our CRM. [We also deleted copies held by our service providers: list them. / Copies held by our service providers were not affected: explain.]</p>
<p><strong>What we kept, and why.</strong> [Keep only what applies: Under the exception for signed contracts, we keep your name and the contract reference [reference] for [period]. / We did not erase [item] because [reason].]</p>
<p><strong>Our record of your request.</strong> As the law requires, we keep a record of this request for 24 months. It holds no contact details. We also keep a do-not-contact entry so your details are not added to our systems again.</p>
<p><strong>A known limitation.</strong> Passing mentions of you inside other people's records, for example a note on a deal, are not searched for or erased.</p>
<p>Sincerely,<br>[Compliance team member]</p>"""


def after_migrate() -> None:
	ensure_compliance_role()
	ensure_secret()
	seed_personal_fields()
	seed_outcome_template()


def ensure_compliance_role() -> None:
	if frappe.db.exists("Role", COMPLIANCE_ROLE):
		return
	frappe.get_doc({"doctype": "Role", "role_name": COMPLIANCE_ROLE, "desk_access": 1}).insert(
		ignore_permissions=True
	)


def seed_personal_fields() -> None:
	"""Fill the personal-fields table from the defaults, only while it is empty.

	Leaving a non-empty table alone means rows an admin removed stay removed.
	"""
	settings = frappe.get_single("CRM Privacy Settings")
	if settings.personal_fields:
		return
	for document_type, fieldnames in DEFAULT_PERSONAL_FIELDS.items():
		for fieldname in fieldnames:
			settings.append("personal_fields", {"document_type": document_type, "fieldname": fieldname})
	settings.save(ignore_permissions=True)


def seed_outcome_template() -> None:
	"""Create the Email Template Compliance sends with the outcome. An existing one is never touched."""
	if frappe.db.exists("Email Template", OUTCOME_TEMPLATE):
		return
	frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": OUTCOME_TEMPLATE,
			"subject": OUTCOME_SUBJECT,
			"use_html": 1,
			"response_html": OUTCOME_HTML,
			"enabled": 1,
			"reference_doctype": "CRM Erasure Request",
		}
	).insert(ignore_permissions=True)

"""Shared test helpers for the privacy (erasure request) tests."""

import frappe

from crm.fcrm.doctype.crm_deal.test_crm_deal import create_test_contact, create_test_deal
from crm.permissions.test_org_hierarchy import make_user

MARISOL_ORG = "Sierra Foothills Dental Group"
MARISOL_EMAIL = "Marisol@SierraFoothills.example"
MARISOL_MOBILE = "(530) 555-0142"


def make_compliance_user(email: str = "privacy.officer@example.com") -> str:
	"""A user holding Compliance and Sales User. Returns the user's name."""
	return make_user(email, ["Compliance", "Sales User"]).name


def make_marisol(owner: str | None = None) -> frappe._dict:
	"""Marisol Vega: one lead, one contact, an open and a won deal, one organization.

	When `owner` is given it owns the lead and both deals, so a Sales User can read them.
	"""
	org = frappe.db.get_value("CRM Organization", {"organization_name": MARISOL_ORG}, "name")
	if not org:
		org = frappe.get_doc({"doctype": "CRM Organization", "organization_name": MARISOL_ORG}).insert().name

	lead_fields = {
		"doctype": "CRM Lead",
		"first_name": "Marisol",
		"last_name": "Vega",
		"email": MARISOL_EMAIL,
		"mobile_no": MARISOL_MOBILE,
		"job_title": "Office Manager",
		"status": "New",
	}
	if owner:
		lead_fields["lead_owner"] = owner
	lead = frappe.get_doc(lead_fields).insert()

	contact = create_test_contact(
		first_name="Marisol", last_name="Vega", email=MARISOL_EMAIL, mobile_no=MARISOL_MOBILE
	)

	def deal(status: str, value: int) -> str:
		fields = {
			"status": status,
			"deal_value": value,
			"organization": org,
			"lead": lead.name,
			"contacts": [{"contact": contact.name}],
		}
		if owner:
			fields["deal_owner"] = owner
		return create_test_deal(**fields).name

	return frappe._dict(
		lead=lead.name,
		contact=contact.name,
		open_deal=deal("Negotiation", 12000),
		won_deal=deal("Won", 8000),
		org=org,
	)


def make_request(**fields) -> "frappe.model.document.Document":
	"""Insert a CRM Erasure Request as the current user."""
	return frappe.get_doc({"doctype": "CRM Erasure Request", **fields}).insert()


def make_communication(
	sender: str,
	reference: tuple[str, str] | None = None,
	recipients: str = "",
	subject: str = "Hello",
	content: str = "Hi",
	**fields,
) -> str:
	"""Insert an email Communication. `reference` is a `(doctype, name)` tuple. Returns its name."""
	values = {
		"doctype": "Communication",
		"sent_or_received": "Sent",
		"communication_medium": "Email",
		"communication_type": "Communication",
		"sender": sender,
		"recipients": recipients,
		"subject": subject,
		"content": content,
	}
	if reference:
		values["reference_doctype"], values["reference_name"] = reference
	values.update(fields)
	return frappe.get_doc(values).insert(ignore_permissions=True).name


def make_email_account(**fields) -> str:
	"""Insert a non-enabled incoming Email Account (`inbox@northpine.example`). Returns its name.

	`create_lead_from_incoming_email` and `create_contact` default to off.
	"""
	values = {
		"doctype": "Email Account",
		"email_account_name": "North Pine Inbox",
		"email_id": "inbox@northpine.example",
		"enable_incoming": 0,
		"enable_outgoing": 0,
		"create_lead_from_incoming_email": 0,
		"create_contact": 0,
	}
	values.update(fields)
	account = frappe.get_doc(values)
	account.flags.ignore_mandatory = True
	account.flags.ignore_validate = True
	return account.insert(ignore_permissions=True).name


def make_note(reference: tuple[str, str], title: str = "Note", content: str = "Note text") -> str:
	"""Insert an FCRM Note on a `(doctype, name)` record. Returns its name."""
	doctype, name = reference
	return (
		frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"title": title,
				"content": content,
				"reference_doctype": doctype,
				"reference_docname": name,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_call_log(**fields) -> str:
	"""Insert a CRM Call Log. Pass `from` through a dict: `make_call_log(**{"from": "..."})`."""
	values = {
		"doctype": "CRM Call Log",
		"id": frappe.generate_hash(length=12),
		"type": "Incoming",
		"status": "Completed",
		"from": "+15550009998",
		"to": "+15550009999",
	}
	values.update(fields)
	return frappe.get_doc(values).insert(ignore_permissions=True).name

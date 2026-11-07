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

	contact = create_test_contact(first_name="Marisol", last_name="Vega", email=MARISOL_EMAIL, mobile_no=MARISOL_MOBILE)

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

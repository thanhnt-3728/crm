# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Shared helper for the privacy tests that need a user with chosen roles."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.install import setup


def make_user(email: str, roles=(), enabled: int = 1) -> str:
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"enabled": enabled,
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	)
	user.insert(ignore_permissions=True)
	return user.name


def make_lead(owner: str | None = None, **values) -> str:
	values.setdefault("first_name", "Marisol")
	values.setdefault("last_name", "Vega")
	lead = frappe.get_doc({"doctype": "CRM Lead", "lead_owner": owner, **values})
	lead.insert(ignore_permissions=True)
	return lead.name


def make_contact(first_name: str, emails=(), phones=(), last_name: str = "Vega") -> str:
	contact = frappe.get_doc({"doctype": "Contact", "first_name": first_name, "last_name": last_name})
	for index, email in enumerate(emails):
		contact.append("email_ids", {"email_id": email, "is_primary": int(index == 0)})
	for index, phone in enumerate(phones):
		contact.append("phone_nos", {"phone": phone, "is_primary_mobile_no": int(index == 0)})
	contact.insert(ignore_permissions=True)
	return contact.name


def make_deal(contacts=(), owner: str | None = None, **values) -> str:
	rows = [{"contact": name, "is_primary": int(index == 0)} for index, name in enumerate(contacts)]
	deal = frappe.get_doc({"doctype": "CRM Deal", "deal_owner": owner, "contacts": rows, **values})
	deal.insert(ignore_permissions=True)
	return deal.name


def make_request(user: str | None = None, **values) -> str:
	"""A Logged request from a blank form, created by `user` (default: the current user)."""
	from crm.api.erasure_requests import create_request

	params = {
		"source_doctype": None,
		"source_name": None,
		"contact": None,
		"channel": "Email",
		"date_received": frappe.utils.today(),
		"requester_names": "Marisol Vega",
		"emails": ["marisol.vega@example.com"],
		"phones": None,
		"original_message": "Please delete my data.",
		**values,
	}
	previous = frappe.session.user
	frappe.set_user(user or previous)
	try:
		return create_request(**params)
	finally:
		frappe.set_user(previous)


def force_request(name: str, **values) -> None:
	"""Set fields straight in the database, the way a fixture needs a state the API would not allow."""
	frappe.db.set_value("CRM Erasure Request", name, values, update_modified=False)


def make_person(owner: str | None = None) -> frappe._dict:
	"""Marisol Vega as the design describes her: a lead, a contact, a deal in Negotiation and a Won one."""
	lead = make_lead(email="m.vega@example.com", mobile_no="+15305550101")
	contact = make_contact("Marisol", emails=["m.vega@example.com"], phones=["+15305550101"])
	return frappe._dict(
		lead=lead,
		contact=contact,
		negotiation=make_deal([contact], owner=owner, status="Negotiation"),
		won=make_deal([contact], status="Won"),
	)


def add_match(name: str, doctype: str, record: str, confirmed: int = 1, relation: str = "Direct") -> None:
	"""Put a match row on a request the way the server would."""
	from crm.privacy.request_status import server_write

	doc = frappe.get_doc("CRM Erasure Request", name)
	doc.append(
		"matches",
		{
			"reference_doctype": doctype,
			"reference_name": record,
			"label": record,
			"confirmed": confirmed,
			"relation": relation,
		},
	)
	with server_write():
		doc.save(ignore_permissions=True)


def match_rows(name: str) -> dict:
	"""{(doctype, name): row} of the request's matches, read fresh from the database."""
	doc = frappe.get_doc("CRM Erasure Request", name)
	return {(m.reference_doctype, m.reference_name): m for m in doc.matches}


def purge_error_logs(since, names=()) -> None:
	"""`frappe.log_error` writes outlive a test's rollback. Remove the erasure-request Error Logs this test
	created: made at or after `since` and naming one of its `names` (or, for a failed lookup, naming no request)."""
	frappe.db.rollback()
	filters = {"reference_doctype": "CRM Erasure Request", "creation": [">=", since]}
	if names:
		frappe.db.delete("Error Log", {**filters, "reference_name": ["in", list(names)]})
	frappe.db.delete("Error Log", {**filters, "reference_name": ["is", "not set"]})
	frappe.db.commit()


def block(*pairs) -> None:
	"""Put `(kind, value)` pairs on the do-not-contact list the way an erasure would (phase 04)."""
	from crm.privacy.do_not_contact import add_entries

	add_entries(pairs)


def forget_dnc_secret() -> None:
	"""Lose the hash key while entries exist, as a restore with another `encryption_key` would."""
	frappe.db.delete("__Auth", {"doctype": "CRM Privacy Settings", "fieldname": "dnc_hash_secret"})


def purge_logs_titled(since, prefix: str) -> None:
	"""Remove the Error Logs this test made (from `since`) whose title starts with `prefix`."""
	frappe.db.delete("Error Log", {"method": ["like", f"{prefix}%"], "creation": [">=", since]})


def as_user(user: str, function, *args, **kwargs):
	"""Call an API function with `user` as the session user."""
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		return function(*args, **kwargs)
	finally:
		frappe.set_user(previous)


class RequestTestCase(IntegrationTestCase):
	"""Users for the four visibility tiers: a logger, another Sales User, a Sales Manager, Compliance."""

	def setUp(self):
		frappe.set_user("Administrator")
		self._started = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=-1)
		setup()
		self.logger = make_user("pdr.logger@example.com", roles=["Sales User"])
		self.other = make_user("pdr.other@example.com", roles=["Sales User"])
		self.manager = make_user("pdr.manager@example.com", roles=["Sales Manager"])
		self.compliance = make_user("pdr.compliance@example.com", roles=["Compliance"])

	def tearDown(self):
		frappe.set_user("Administrator")
		names = frappe.get_all("CRM Erasure Request", pluck="name")
		frappe.db.rollback()
		if frappe.db.exists(
			"Error Log", {"reference_doctype": "CRM Erasure Request", "creation": [">=", self._started]}
		):
			purge_error_logs(self._started, names)

	def submitted_request(self, user: str | None = None, status: str = "Awaiting sign-off") -> str:
		"""A request the logger has already submitted (state set directly: the submit API arrives in phase 03)."""
		name = make_request(user or self.logger)
		force_request(name, status=status)
		return name

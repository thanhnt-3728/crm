# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Shared fixtures for the erasure request tests (not a test module itself)"""

from contextlib import contextmanager

import frappe
from frappe.utils import today

from crm.install import add_privacy_officer_role

REP = "erq.rep@example.com"
REP2 = "erq.rep2@example.com"
PO = "erq.po@example.com"
PO_REP = "erq.po.rep@example.com"
MANAGER = "erq.manager@example.com"

USER_ROLES = {
	REP: ("Sales User",),
	REP2: ("Sales User",),
	PO: ("Sales User", "Privacy Officer"),
	PO_REP: ("Sales User", "Privacy Officer"),
	MANAGER: ("Sales Manager",),
}


def ensure_users():
	add_privacy_officer_role()
	for email, roles in USER_ROLES.items():
		if frappe.db.exists("User", email):
			continue
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles(*roles)


@contextmanager
def as_user(user):
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous)


def make_contact(first_name="Dana"):
	return frappe.get_doc({"doctype": "Contact", "first_name": first_name}).insert(ignore_permissions=True)


def make_lead(first_name="Dana", lead_owner=REP):
	"""Owned by REP by default: a Sales User reads only leads they own or are assigned.
	Created as the owner, so the self-assignment raises no CRM Notification that blocks deletes."""
	return _insert_as(lead_owner, {"doctype": "CRM Lead", "first_name": first_name, "lead_owner": lead_owner})


def make_deal(**fields):
	fields.setdefault("deal_owner", REP)
	return _insert_as(fields["deal_owner"], {"doctype": "CRM Deal", **fields})


def _insert_as(user, doc):
	with as_user(user or "Administrator"):
		return frappe.get_doc(doc).insert(ignore_permissions=True)


SOURCE_EMAIL_FIELDS = {"CRM Lead": "email", "CRM Deal": "email", "Contact": "email_id"}
REQUEST_EMAIL = "dana.test@example.com"


def make_request(source_doctype, source_docname, matches=(), **fields):
	"""Insert a Draft request as the current session user; matches are (doctype, name[, excluded])

	The source gets the request's email (raw), as `log_request` requires one identifier on it.
	"""
	if frappe.db.exists(source_doctype, source_docname):
		field = SOURCE_EMAIL_FIELDS[source_doctype]
		frappe.db.set_value(source_doctype, source_docname, field, REQUEST_EMAIL, update_modified=False)
	doc = frappe.get_doc(
		{
			"doctype": "CRM Erasure Request",
			"subject_name": "Dana Test",
			"source_doctype": source_doctype,
			"source_docname": source_docname,
			"received_on": today(),
			"identifiers": [{"kind": "Email", "value": REQUEST_EMAIL}],
		}
	)
	doc.update(fields)
	doc.insert()
	if matches:
		doc.replace_matches(
			[{"ref_doctype": m[0], "ref_name": m[1], "excluded": m[2] if len(m) > 2 else 0} for m in matches]
		)
	return doc


def ensure_lost_reason():
	name = frappe.db.get_value("CRM Lost Reason", {"name": ["!=", "Other"]}, "name")
	if name:
		return name
	return frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": "Erasure Test"}).insert().name


def set_deal_status(deal_name, status):
	deal = frappe.get_doc("CRM Deal", deal_name)
	deal.status = status
	if frappe.db.get_value("CRM Deal Status", status, "type") == "Lost":
		deal.lost_reason = ensure_lost_reason()
	deal.save(ignore_permissions=True)
	return deal


def ensure_deal_status(name, status_type):
	if not frappe.db.exists("CRM Deal Status", name):
		frappe.get_doc({"doctype": "CRM Deal Status", "deal_status": name, "type": status_type}).insert()
	return name


def approve(request, user=PO):
	with as_user(user):
		request.reload()
		request.transition_to("Approved", approver=user, approved_on=frappe.utils.now_datetime())
	return request

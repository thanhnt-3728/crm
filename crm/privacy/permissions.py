"""Who may see and change erasure requests. Every check is by user, server-side."""

from typing import Literal

import frappe

DOCTYPE = "CRM Erasure Request"
FULL_ACCESS_ROLES = ("Compliance", "Sales Manager")


def _roles(user: str | None) -> list[str]:
	return frappe.get_roles(user or frappe.session.user)


def is_compliance(user: str | None = None) -> bool:
	return "Compliance" in _roles(user)


def access_level(doc, user: str | None = None) -> Literal["full", "summary"] | None:
	"""How much of a request `user` may see.

	Compliance is checked before the logger rules, so a Compliance user who logged the
	request still gets the full view.
	"""
	user = user or frappe.session.user
	roles = _roles(user)
	if "Compliance" in roles or "Sales Manager" in roles:
		return "full"
	if doc.logged_by == user:
		return "full" if doc.status == "Logged" else "summary"
	return None


def has_permission(doc, ptype: str, user: str | None = None) -> bool:
	user = user or frappe.session.user
	roles = _roles(user)
	if "Compliance" in roles:
		return True
	if ptype == "create":
		return "Sales User" in roles
	if isinstance(doc, str):
		doc = frappe.db.get_value(DOCTYPE, doc, ["logged_by", "status"], as_dict=True)
	if not doc:
		return False
	if "Sales Manager" in roles and ptype == "read":
		return True
	if doc.logged_by == user and doc.status == "Logged":
		return ptype in ("read", "write")
	return False


def get_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	roles = _roles(user)
	if "Compliance" in roles or "Sales Manager" in roles:
		return ""
	return (
		f"(`tab{DOCTYPE}`.logged_by = {frappe.db.escape(user)} and `tab{DOCTYPE}`.status = 'Logged')"
	)

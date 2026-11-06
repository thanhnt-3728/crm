from contextlib import contextmanager

import frappe


def settings():
	"""The CRM Privacy Settings single, cached."""
	return frappe.get_cached_doc("CRM Privacy Settings")


def personal_fields(doctype: str) -> set[str]:
	"""Fieldnames of `doctype` that hold personal data, per the privacy settings."""
	return {row.fieldname for row in settings().personal_fields if row.document_type == doctype}


def has_compliance_role(user: str | None = None) -> bool:
	"""Whether `user` (default: the session user) is assigned the Compliance role.

	Reads the role assignment itself: `frappe.get_roles("Administrator")` returns every
	role, and the Administrator must not pass as Compliance through that."""
	user = user or frappe.session.user
	return bool(frappe.db.exists("Has Role", {"parenttype": "User", "parent": user, "role": "Compliance"}))


def compliance_users() -> list[str]:
	"""Enabled users who hold the Compliance role."""
	holders = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": "Compliance"},
		pluck="parent",
		distinct=True,
	)
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")


@contextmanager
def system_write():
	"""Mark saves inside the block as made by the privacy system, not by a user.

	CRM Erasure Request refuses user writes to its status, approval and bookkeeping fields;
	code that legitimately moves them (submit, approve, erasure job, reminders) wraps its
	save in this. The previous flag value is restored on exit, so blocks nest."""
	previous = frappe.flags.privacy_system_write
	frappe.flags.privacy_system_write = True
	try:
		yield
	finally:
		frappe.flags.privacy_system_write = previous

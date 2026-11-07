# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Explicit role checks for the Compliance role.

`frappe.get_roles("Administrator")` returns every role, so it must not be used to decide who is
Compliance: Administrator and System Manager would be able to approve erasures without being
assigned. These helpers read the `Has Role` rows on the User instead (design 5.1).
"""

import frappe

COMPLIANCE_ROLE = "Compliance"


def has_explicit_role(user: str | None, role: str | None) -> bool:
	"""True only when `user` has a `Has Role` row for `role`. Never inferred from Administrator or System Manager."""
	if not user or not role:
		return False
	return bool(frappe.db.exists("Has Role", {"parenttype": "User", "parent": user, "role": role}))


def get_compliance_users() -> list[str]:
	"""Enabled CRM (System) users with an explicit Compliance role row. Guest and Administrator are
	never listed, even if a row exists, so notifications go to real people."""
	holders = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": COMPLIANCE_ROLE},
		pluck="parent",
	)
	if not holders:
		return []
	return frappe.get_all(
		"User",
		filters=[
			["name", "in", [h for h in holders if h not in ("Guest", "Administrator")]],
			["enabled", "=", 1],
			["user_type", "=", "System User"],
		],
		pluck="name",
		order_by="name",
	)

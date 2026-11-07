# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Who holds Compliance: listing, and granting or revoking it (V1).

Only a System Manager changes membership, never for themselves, and each change leaves a Comment on the privacy
settings that names who granted or revoked whom. The grant is an explicit `Has Role` row, the only thing the
approval check accepts (see `crm.privacy.roles`).
"""

import re

import frappe
from frappe import _
from frappe.utils import strip_html_tags

from crm.api.user import validate_no_role_profile
from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import SETTINGS
from crm.privacy.roles import COMPLIANCE_ROLE, has_explicit_role

MANAGER_ROLE = "System Manager"
# English on purpose: the audit trail must stay readable by `audited_holders` whatever language wrote it.
GRANTED, REVOKED = "{0} granted the Compliance role to {1}", "{0} revoked the Compliance role from {1}"
AUDIT_LINE = re.compile(r"(?P<verb>granted|revoked) the Compliance role (?:to|from) (?P<user>\S+)$")


def require_system_manager(user: str) -> None:
	if MANAGER_ROLE not in frappe.get_roles(user):
		frappe.throw(_("Only a System Manager can manage the privacy settings"), frappe.PermissionError)


def list_members() -> list[dict]:
	"""Every user with an explicit Compliance row, as `{user, full_name, enabled}`, by name."""
	holders = frappe.get_all(
		"Has Role", {"parenttype": "User", "role": COMPLIANCE_ROLE}, pluck="parent", distinct=True
	)
	if not holders:
		return []
	rows = frappe.get_all(
		"User",
		{"name": ["in", holders]},
		["name as user", "full_name", "enabled"],
		order_by="full_name asc, name asc",
	)
	return [{"user": r.user, "full_name": r.full_name, "enabled": bool(r.enabled)} for r in rows]


def _check_target(user: str, enabled: bool) -> None:
	if not frappe.db.exists("User", user):
		frappe.throw(_("User {0} not found").format(user), frappe.DoesNotExistError)
	if enabled:
		if user in frappe.STANDARD_USERS:  # a shared account must not approve: it is never notified
			frappe.throw(_("{0} cannot be a Compliance member").format(user))
		info = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
		if not info.enabled or info.user_type != "System User":
			frappe.throw(_("Only an enabled system user can be made a Compliance member"))


def _audit(actor: str, user: str, enabled: bool) -> None:
	frappe.get_doc(SETTINGS).add_comment("Info", (GRANTED if enabled else REVOKED).format(actor, user))


def set_member(user: str, enabled: bool, actor: str) -> list[dict]:
	"""Grant or revoke Compliance for `user`, on behalf of `actor` (the session user). Returns the members."""
	require_system_manager(actor)
	if (user or "").lower() == (actor or "").lower():
		frappe.throw(_("You cannot change your own Compliance role"), frappe.PermissionError)
	enabled = bool(enabled)
	_check_target(user, enabled)

	target = frappe.get_doc("User", user)
	validate_no_role_profile(target)  # a save would re-derive the roles from the profile and undo the change
	if has_explicit_role(user, COMPLIANCE_ROLE) != enabled:
		target.flags.ignore_permissions = True
		if enabled:
			target.add_roles(COMPLIANCE_ROLE)
		else:
			target.remove_roles(COMPLIANCE_ROLE)
		# the audit says what happened, so it is written only when the roles really changed
		if has_explicit_role(user, COMPLIANCE_ROLE) != enabled:
			frappe.throw(_("The Compliance role of {0} could not be changed").format(user))
		_audit(actor, user, enabled)
	return list_members()


def audited_holders() -> set[str]:
	"""Users whose latest audit Comment on the privacy settings is a grant."""
	comments = frappe.get_all(
		"Comment",
		{"reference_doctype": SETTINGS, "reference_name": SETTINGS, "comment_type": "Info"},
		pluck="content",
		order_by="creation asc, name asc",
	)
	state = {}
	for content in comments:
		if found := AUDIT_LINE.search(strip_html_tags(content or "").strip()):
			state[found["user"]] = found["verb"] == "granted"
	return {user for user, granted in state.items() if granted}


def revoke_unaudited_grants(args=None) -> int:
	"""`setup_wizard_complete` hook. The wizard gives its first user every Role that exists, Compliance included,
	which would let that user approve irreversible erasures with no grant on record (M1). Take the role back from
	every holder without a grant Comment, and leave one Comment with the count (no names). Returns the count."""
	audited = audited_holders()
	holders = frappe.get_all(
		"Has Role", {"parenttype": "User", "role": COMPLIANCE_ROLE}, pluck="parent", distinct=True
	)
	unaudited = [user for user in holders if user not in audited]
	if not unaudited:
		return 0
	frappe.db.delete("Has Role", {"parenttype": "User", "role": COMPLIANCE_ROLE, "parent": ["in", unaudited]})
	for user in unaudited:
		frappe.clear_cache(user=user)
	frappe.get_doc(SETTINGS).add_comment(
		"Info",
		f"Removed the Compliance role from {len(unaudited)} user(s) the setup wizard gave it to. "
		"Grant it on the Privacy page.",
	)
	return len(unaudited)

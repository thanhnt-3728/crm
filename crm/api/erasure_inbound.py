# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Compliance reads the inbound mail it is told about (design 5.9), through two endpoints and nothing broader.

Mailbox sync owns every Communication as Administrator, and on v16 only System Manager, Inbox User or the
owner can read one, so Compliance has no standard way in. No DocPerm is granted on Communication (that would
open every mailbox). Instead each endpoint checks, by an explicit `Has Role` row, that the caller is Compliance,
and only ever returns mail that exists for the erasure workflow:

* mail attached to a CRM Erasure Request (an open request's confirmed email wrote to us), and
* mail detached by the do-not-contact list: received, linked to nothing, and sent from a listed address.

Phase 07: a CRM Notification of type `Compliance` whose `reference_doctype` is `Communication` opens that mail
with `get_inbound_communication(name)`; a request's page lists its mail with `list_request_communications(name)`.
"""

import frappe
from frappe import _

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import DncSecretUnavailableError
from crm.privacy.do_not_contact import PrivacySettingsIncompleteError, is_blocked
from crm.privacy.inbound_email import sender_address
from crm.privacy.request_visibility import DOCTYPE
from crm.privacy.roles import COMPLIANCE_ROLE, has_explicit_role

FIELDS = (
	"name",
	"sender",
	"sender_full_name",
	"recipients",
	"cc",
	"bcc",
	"subject",
	"content",
	"communication_date",
	"sent_or_received",
	"communication_type",
	"reference_doctype",
	"reference_name",
)


def _require_compliance() -> None:
	if not has_explicit_role(frappe.session.user, COMPLIANCE_ROLE):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _is_detached_inbound(mail) -> bool:
	"""Received, linked to nothing, and from an address on the do-not-contact list."""
	if mail.reference_doctype or mail.reference_name:
		return False
	if mail.sent_or_received != "Received" or mail.communication_type != "Communication":
		return False
	try:
		return is_blocked("email", sender_address(mail))
	except DncSecretUnavailableError:
		frappe.throw(_("Privacy settings are incomplete. Ask your administrator."), PrivacySettingsIncompleteError)


@frappe.whitelist()
def get_inbound_communication(name: str) -> dict:
	"""One inbound mail: sender, recipients, subject, content, date and what it is linked to. Compliance only,
	and only mail linked to an erasure request or detached by the do-not-contact list."""
	_require_compliance()
	mail = frappe.db.get_value("Communication", name, list(FIELDS), as_dict=True)
	if not mail:
		frappe.throw(_("Email {0} not found").format(name), frappe.DoesNotExistError)
	linked = mail.reference_doctype == DOCTYPE and mail.reference_name
	if not (linked or _is_detached_inbound(mail)):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return dict(mail)


@frappe.whitelist()
def list_request_communications(name: str) -> list[dict]:
	"""The mail attached to one erasure request, oldest first. Compliance only."""
	_require_compliance()
	if not frappe.db.exists(DOCTYPE, name):
		frappe.throw(_("Request {0} not found").format(name), frappe.DoesNotExistError)
	rows = frappe.get_all(
		"Communication",
		{"reference_doctype": DOCTYPE, "reference_name": name},
		list(FIELDS),
		order_by="communication_date asc, creation asc",
	)
	return [dict(row) for row in rows]

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""CRM notification plus email for the On Hold loop (design 5.2).

Erasure requests cannot be shared or assigned, so people are told through a CRM Notification and an
email. A body names the PDR number and the deal and nothing else: no requester name, email or phone
(RT-10). Phase 05 deletes these notices and queued emails when the request is erased.
"""

import frappe
from frappe import _
from frappe.utils import escape_html

from crm.privacy.error_log import log_privacy_error
from crm.privacy.roles import get_compliance_users

DOCTYPE = "CRM Erasure Request"
CONTACT_HOLD, CONFIRMED_HOLD, SOURCE_HOLD = "contact", "confirmed", "source"


def hold_text(request: str, deal: str, why: str) -> str:
	"""What a deal owner is asked to do. `why` says whether the deal holds the request because it lists the
	person (remove them, or close the deal), because it was confirmed as a match (close it, or unconfirm it) or
	because the request was started from it (close it: that row cannot be unconfirmed)."""
	if why == SOURCE_HOLD:
		return _(
			"{0}: deal {1} is the record a privacy erasure request was started from and is still open. "
			"Close the deal so the request can go ahead."
		).format(request, deal)
	if why == CONFIRMED_HOLD:
		return _(
			"{0}: deal {1} is part of a privacy erasure request and is still open. Close the deal, "
			"or ask Compliance to unconfirm it, so the request can go ahead."
		).format(request, deal)
	return _(
		"{0}: deal {1} lists a person with an open privacy erasure request. Remove their contact "
		"from the deal, or close the deal, so the request can go ahead."
	).format(request, deal)


def _notice(user: str, request: str, link_doctype: str, link_name: str) -> dict:
	return {
		"type": "Compliance",
		"to_user": user,
		"notification_type_doctype": DOCTYPE,
		"notification_type_doc": request,
		"reference_doctype": link_doctype,
		"reference_name": link_name,
	}


def has_hold_notice(request: str, deal: str, owner: str) -> bool:
	"""Whether `owner` was already told about `deal` for this request."""
	return bool(frappe.db.exists("CRM Notification", _notice(owner, request, "CRM Deal", deal)))


def notify_users(
	users, text: str, *, request: str, link_doctype: str, link_name: str, dedupe: bool = False
) -> int:
	"""Notify each enabled user once per call. With `dedupe`, a user who already has this notice for this
	request and record is skipped. Returns how many were notified."""
	sent = 0
	for user in dict.fromkeys(users):
		if not (user and frappe.db.get_value("User", user, "enabled")):
			continue
		notice = _notice(user, request, link_doctype, link_name)
		if dedupe and frappe.db.exists("CRM Notification", notice):
			continue
		body = escape_html(text)
		frappe.get_doc(
			{"doctype": "CRM Notification", **notice, "message": body, "notification_text": body}
		).insert(ignore_permissions=True)
		_send_email(user, text, request)
		sent += 1
	return sent


def _send_email(user: str, text: str, request: str) -> None:
	failed = None
	try:
		frappe.sendmail(
			recipients=[user],
			subject=_("{0}: privacy erasure request").format(request),
			message=escape_html(text),
			reference_doctype=DOCTYPE,
			reference_name=request,
		)
	except Exception as error:  # mail setup must not stop the CRM notification (PII-free log)
		failed = type(error).__name__
	if failed:
		log_privacy_error(request, failed, reference_doctype=DOCTYPE, reference_name=request)


def deliver_hold_notices(request: str, notices: list, awaiting: bool) -> None:
	"""Tell each deal owner in `notices` ([deal, owner, why]) what to do, and Compliance that the request awaits
	sign-off when `awaiting`."""
	for deal, owner, why in notices:
		notify_users(
			[owner],
			hold_text(request, deal, why),
			request=request,
			link_doctype="CRM Deal",
			link_name=deal,
			dedupe=True,
		)
	if awaiting:
		text = _("{0} awaits sign-off").format(request)
		notify_users(get_compliance_users(), text, request=request, link_doctype=DOCTYPE, link_name=request)

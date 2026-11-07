# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Daily reminders on open erasure requests (design 5.5, phase 06; V1).

Each reminder is sent once per request (a hidden flag), as a CRM Notification and an email (`notify.notify_users`):

* acknowledgment: three business days before *acknowledge by*, unless the acknowledgment was recorded;
* day 30 (received + 30): all Compliance users;
* day 40 (received + 40): the Head of Compliance, or all Compliance users when none is set or enabled.

The comparisons are `>=`, so a request logged late (or a run that was missed) gets what is already due on the
next run. Text carries the request number and dates only. Each request runs on its own: a failure is logged with
the request number and the exception class and the rest of the run goes on. A flag is set in the same transaction
as the notification, only after something was sent.
"""

import frappe
from frappe import _
from frappe.utils import add_days, formatdate, getdate

from crm.privacy import notify
from crm.privacy.business_days import acknowledge_by, respond_by, subtract_business_days
from crm.privacy.error_log import log_privacy_error
from crm.privacy.on_hold import _isolated
from crm.privacy.request_status import CLOSED
from crm.privacy.request_visibility import DOCTYPE
from crm.privacy.roles import get_compliance_users

ACK, DAY30, DAY40 = "ack", "day30", "day40"
FLAGS = {ACK: "ack_reminder_sent", DAY30: "day30_reminder_sent", DAY40: "day40_alert_sent"}
ACK_LEAD_BUSINESS_DAYS = 3
DAY30_AFTER, DAY40_AFTER = 30, 40
SETTINGS = "CRM Privacy Settings"
FIELDS = [
	"name",
	"status",
	"date_received",
	"acknowledge_by",
	"respond_by",
	"acknowledgment_sent",
	*FLAGS.values(),
]


def due_reminders(request, today) -> list[str]:
	"""Which reminders (`ack`, `day30`, `day40`, in that order) are due for `request` on `today`. `request` is a
	dict, `_dict` or document with the fields in `FIELDS`; nothing is read from the database."""
	if request.get("status") == CLOSED:
		return []
	today, received = getdate(today), getdate(request.get("date_received"))
	ack_by = getdate(request.get("acknowledge_by") or acknowledge_by(received))
	due = {
		ACK: not request.get("acknowledgment_sent")
		and today >= subtract_business_days(ack_by, ACK_LEAD_BUSINESS_DAYS),
		DAY30: today >= add_days(received, DAY30_AFTER),
		DAY40: today >= add_days(received, DAY40_AFTER),
	}
	return [kind for kind, is_due in due.items() if is_due and not request.get(FLAGS[kind])]


def reminder_text(kind: str, request) -> str:
	respond = formatdate(request.get("respond_by") or respond_by(getdate(request.get("date_received"))))
	if kind == ACK:
		by = formatdate(
			request.get("acknowledge_by") or acknowledge_by(getdate(request.get("date_received")))
		)
		return _("{0}: acknowledge the request by {1}").format(request.name, by)
	days = DAY30_AFTER if kind == DAY30 else DAY40_AFTER
	return _("{0}: {1} days since the request was received. Respond by {2}").format(
		request.name, days, respond
	)


def day40_recipients(request: str) -> list[str]:
	"""The Head of Compliance when set and enabled; otherwise every Compliance user, with an Error Log entry so an
	administrator sees that the setting needs attention."""
	head = frappe.db.get_single_value(SETTINGS, "head_of_compliance")
	if head and frappe.db.get_value("User", head, "enabled"):
		return [head]
	log_privacy_error(
		request, "HeadOfComplianceUnavailable", reference_doctype=DOCTYPE, reference_name=request
	)
	return get_compliance_users()


def deliver(request) -> None:
	"""Send what is due on `request` (a fresh, locked row) and set each flag after its send."""
	for kind in due_reminders(request, request.today):
		users = day40_recipients(request.name) if kind == DAY40 else get_compliance_users()
		sent = notify.notify_users(
			users,
			reminder_text(kind, request),
			request=request.name,
			link_doctype=DOCTYPE,
			link_name=request.name,
		)
		if sent:
			frappe.db.set_value(DOCTYPE, request.name, FLAGS[kind], 1, update_modified=False)
		else:  # nobody to tell: leave the flag so the next run tries again
			log_privacy_error(
				request.name, "NoReminderRecipient", reference_doctype=DOCTYPE, reference_name=request.name
			)


def send_due_reminders(today=None) -> None:
	"""The daily job. Flags are single-field writes (`set_value`): a reminder never rewrites a request that an
	approval, the erasure job or a close may be changing."""
	day = getdate(today)
	for name in frappe.get_all(DOCTYPE, {"status": ["!=", CLOSED]}, pluck="name", order_by="creation asc"):
		with _isolated(name, name):
			request = frappe.db.get_value(DOCTYPE, name, FIELDS, as_dict=True, for_update=True)
			if request and request.status != CLOSED:
				deliver(frappe._dict(request, today=day))
		frappe.db.commit()  # nosemgrep: per request, so no row stays locked while the run goes on

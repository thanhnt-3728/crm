"""Daily reminders for open erasure requests.

Compliance is warned before a deadline is missed. Each reminder goes out once per request,
as a CRM notification and an email, and only while the request is not Closed:

- acknowledgment: 3 business days before *acknowledge by*, if not yet acknowledged
- day 30: all Compliance users
- day 40: the Head of Compliance (all Compliance users if none is set)

A request logged late gets every reminder that is already due on the next run. The messages
carry the request number and dates only, never the requester's details.
"""

from datetime import date

import frappe
from frappe.utils import getdate

from crm.privacy import compliance_users
from crm.privacy.deadlines import (
	RESPOND_CALENDAR_DAYS,
	acknowledge_by,
	day_number,
	days_left,
	respond_by,
	subtract_business_days,
)
from crm.privacy.notify import notify

REQUEST = "CRM Erasure Request"
ACK_REMINDER_BUSINESS_DAYS = 3
SAVEPOINT = "privacy_reminder"
DAY30 = 30
DAY40 = 40


def send_due_reminders(today: date | None = None) -> None:
	"""Send every reminder that is due and not yet sent for each open request."""
	today = getdate(today) if today else getdate(frappe.utils.today())
	requests = frappe.get_all(
		REQUEST,
		filters={"status": ["!=", "Closed"]},
		fields=[
			"name",
			"received_on",
			"acknowledge_by",
			"respond_by",
			"acknowledgment_sent",
			"ack_reminder_sent",
			"day30_reminder_sent",
			"day40_alert_sent",
		],
	)
	for row in requests:
		if not row.received_on:
			continue
		try:
			frappe.db.savepoint(SAVEPOINT)
			_remind(row, today)
		except Exception:
			frappe.db.rollback(save_point=SAVEPOINT)
			# One request must not stop the others. Fixed message: no traceback with locals.
			frappe.log_error(
				title="Erasure reminder failed",
				message=f"Could not send reminders for erasure request {row.name}.",
			)


def _remind(row, today: date) -> None:
	received = getdate(row.received_on)
	ack_by = getdate(row.acknowledge_by) if row.acknowledge_by else acknowledge_by(received)
	resp_by = getdate(row.respond_by) if row.respond_by else respond_by(received)
	left = days_left(received, today)
	elapsed = day_number(received, today)
	respond_text = f"{left} of {RESPOND_CALENDAR_DAYS} days left — respond by {resp_by}"

	if (
		not row.acknowledgment_sent
		and not row.ack_reminder_sent
		and today >= subtract_business_days(ack_by, ACK_REMINDER_BUSINESS_DAYS)
	):
		_send(
			row.name,
			"ack_reminder_sent",
			compliance_users(),
			f"Erasure request {row.name}: acknowledgment due",
			f"{row.name}: {left} of {RESPOND_CALENDAR_DAYS} days left — acknowledge by {ack_by}",
		)

	if not row.day30_reminder_sent and elapsed >= DAY30:
		_send(
			row.name,
			"day30_reminder_sent",
			compliance_users(),
			f"Erasure request {row.name}: day 30",
			f"{row.name}: {respond_text}",
		)

	if not row.day40_alert_sent and elapsed >= DAY40:
		_send(
			row.name,
			"day40_alert_sent",
			_day40_recipients(),
			f"Erasure request {row.name}: day 40",
			f"{row.name}: {respond_text}",
		)


def _day40_recipients() -> list[str]:
	"""The Head of Compliance, or every Compliance user when none is set (never dropped)."""
	head = frappe.db.get_single_value("CRM Privacy Settings", "head_of_compliance")
	if head and frappe.db.get_value("User", head, "enabled"):
		return [head]
	return compliance_users()


def _send(request: str, flag: str, users: list[str], subject: str, message: str) -> None:
	"""Notify, then mark the reminder sent, so a failure retries on the next run."""
	if not users:
		# Nobody to tell yet: leave the flag off so it goes out once someone holds the role.
		return
	notify(users, subject, message, request=request)
	frappe.db.set_value(REQUEST, request, flag, 1, update_modified=False)

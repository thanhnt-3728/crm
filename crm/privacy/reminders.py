"""Notices sent to users about erasure requests.

Notices name the request number only. The one exception is the On Hold notice to a deal
owner (see `crm.privacy.hold`), which names the contact.
"""

import frappe
from frappe.utils import getdate

from crm.privacy.deadlines import days_left, reminder_dates
from crm.privacy.identifiers import compliance_users

DOCTYPE = "CRM Erasure Request"


def notify(
	users: list[str],
	subject: str,
	request: str,
	reference_doctype: str = DOCTYPE,
	reference_name: str | None = None,
) -> None:
	"""Send each user a CRM Notification and one email. `request` is the request's name."""
	if not users:
		return

	for user in users:
		frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"type": "Privacy",
				"from_user": "Administrator",
				"to_user": user,
				"notification_text": subject,
				"message": subject,
				"notification_type_doctype": DOCTYPE,
				"notification_type_doc": request,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name or request,
			}
		).insert(ignore_permissions=True)

	frappe.sendmail(
		recipients=users,
		subject=subject,
		message=subject,
		reference_doctype=DOCTYPE,
		reference_name=request,
	)


def send_reminders(today=None) -> None:
	"""Daily: send each due reminder once for every request that is not Closed.

	Order is acknowledgment, day 30, day 40, so a request logged late gets every reminder
	that is already due in one run. Each request is handled on its own; a failure is logged
	(by request number only) and the others still go out.
	"""
	today = getdate(today)
	requests = frappe.get_all(
		DOCTYPE,
		filters={"status": ["!=", "Closed"]},
		fields=[
			"name",
			"date_received",
			"acknowledge_by",
			"acknowledgment_sent",
			"ack_reminder_sent",
			"day30_reminder_sent",
			"day40_alert_sent",
		],
		order_by="creation asc",
	)
	for request in requests:
		try:
			_remind(request, today)
		except Exception:
			# A fixed message keeps the traceback (and its local variables) out of the Error Log.
			frappe.log_error(
				title=f"Erasure reminder failed for {request.name}",
				message="A reminder could not be sent. It is retried on the next daily run.",
				reference_doctype=DOCTYPE,
				reference_name=request.name,
			)


def _remind(request, today) -> None:
	received = getdate(request.date_received)
	due = reminder_dates(received)
	text = f"Erasure request {request.name}: {days_left(received, today)} of 45 days left"

	if not request.acknowledgment_sent and not request.ack_reminder_sent and today >= due["acknowledgment"]:
		subject = f"Erasure request {request.name}: acknowledge by {request.acknowledge_by}"
		_send_once(request.name, "ack_reminder_sent", compliance_users(), subject)

	if not request.day30_reminder_sent and today >= due["day_30"]:
		_send_once(request.name, "day30_reminder_sent", compliance_users(), text)

	if not request.day40_alert_sent and today >= due["day_40"]:
		_send_once(request.name, "day40_alert_sent", _day_40_recipients(), text)


def _day_40_recipients() -> list[str]:
	"""The Head of Compliance when set and enabled, otherwise every Compliance user."""
	head = frappe.db.get_single_value("CRM Privacy Settings", "head_of_compliance")
	if head and frappe.db.get_value("User", head, "enabled"):
		return [head]
	return compliance_users()


def _send_once(request: str, flag: str, users: list[str], subject: str) -> None:
	"""Notify, then set the flag, as one unit: a failure in between undoes both.

	Nothing is sent and no flag is set when there is nobody to notify, so the reminder
	goes out once a Compliance user exists.
	"""
	if not users:
		return
	savepoint = "erasure_reminder"
	frappe.db.savepoint(savepoint)
	try:
		notify(users, subject, request)
		# A protected field: written directly, never through doc.save().
		frappe.db.set_value(DOCTYPE, request, flag, 1, update_modified=False)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	else:
		frappe.db.release_savepoint(savepoint)

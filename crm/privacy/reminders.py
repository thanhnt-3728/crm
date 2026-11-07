"""Notices sent to users about erasure requests.

Notices name the request number only. The one exception is the On Hold notice to a deal
owner (see `crm.privacy.hold`), which names the contact.
"""

import frappe

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

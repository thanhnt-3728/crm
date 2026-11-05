import frappe


def notify(
	users: list[str],
	subject: str,
	message: str,
	request: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> None:
	"""Tell `users` about a privacy event: one CRM Notification each, plus one email.

	The notification links to `reference_doctype`/`reference_name` when given, else to the
	erasure request `request` if that record exists.
	"""
	users = list(dict.fromkeys(users or []))
	if not users:
		return

	if (
		not reference_doctype
		and request
		and frappe.db.exists("DocType", "CRM Erasure Request")
		and frappe.db.exists("CRM Erasure Request", request)
	):
		reference_doctype, reference_name = "CRM Erasure Request", request

	for user in users:
		frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"from_user": "Administrator",
				"to_user": user,
				"type": "Privacy",
				"notification_text": subject,
				"message": message,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
			}
		).insert(ignore_permissions=True)

	frappe.sendmail(recipients=users, subject=subject, message=message)

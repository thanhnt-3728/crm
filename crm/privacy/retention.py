"""Daily purge of what the 24-month and contract retention periods have run out for."""

from datetime import date

import frappe
from frappe.utils import getdate

REQUEST = "CRM Erasure Request"
RETAINED_CONTRACT = "CRM Retained Contract"


def purge_expired(today: date | None = None) -> None:
	"""Delete closed log entries and retained-contract entries past their delete-after date.

	An entry with no delete-after date is kept. Deletion is permanent: no Deleted Document
	copy is made. One failed deletion does not stop the rest."""
	today = getdate(today) if today else getdate(frappe.utils.today())
	expired_requests = frappe.get_all(
		REQUEST, filters={"status": "Closed", "delete_after": ["<=", today]}, pluck="name"
	)
	for name in expired_requests:
		_delete(REQUEST, name)
	expired_contracts = frappe.get_all(
		RETAINED_CONTRACT, filters={"delete_after": ["<=", today]}, pluck="name"
	)
	for name in expired_contracts:
		_delete(RETAINED_CONTRACT, name)


def _delete(doctype: str, name: str) -> None:
	try:
		frappe.db.savepoint("privacy_purge")
		if doctype == REQUEST:
			# Notifications about the request would otherwise block its deletion.
			frappe.db.delete("CRM Notification", {"reference_doctype": REQUEST, "reference_name": name})
		frappe.delete_doc(doctype, name, delete_permanently=True, ignore_permissions=True, force=True)
	except Exception:
		frappe.db.rollback(save_point="privacy_purge")
		# Fixed message: no traceback with locals, nothing personal.
		frappe.log_error(
			title="Erasure retention purge failed",
			message=f"Could not delete {doctype} {name}.",
		)

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Base case for the purge tests: closed requests, retained contracts and a `delete_doc` that can fail."""

from unittest.mock import patch

import frappe
from frappe.utils import today

from crm.privacy.retention import purge_expired
from crm.privacy.tests.erasure_fixture import remove_bytes
from crm.privacy.tests.error_log_watch import ErrorLogWatch
from crm.privacy.tests.make_test_user import RequestTestCase, force_request, make_request

DOCTYPE, CONTRACT = "CRM Erasure Request", "CRM Retained Contract"
REAL_DELETE = frappe.delete_doc


def deleted_copies(doctype: str, name: str) -> int:
	return frappe.db.count("Deleted Document", {"deleted_doctype": doctype, "deleted_name": name})


class RetentionCase(ErrorLogWatch, RequestTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(remove_bytes)
		super().setUp()
		self.watch_error_logs()
		enqueue = patch("frappe.enqueue")
		enqueue.start()
		self.addCleanup(enqueue.stop)

	def closed(self, purge_after=None, **values) -> str:
		name = make_request(self.logger)
		values.setdefault("status", "Closed")
		force_request(name, closed_on=today(), purge_after=purge_after or today(), **values)
		return name

	def contract(self, delete_after=None, request=None) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": CONTRACT,
					"person_name": "Marisol Vega",
					"contract_reference": f"CT-{frappe.generate_hash(length=6)}",
					"delete_after": delete_after or today(),
					"request": request,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def run_job(self, day=None):
		purge_expired(day)

	def exists(self, name) -> bool:
		return bool(frappe.db.exists(DOCTYPE, name))

	def failing_delete(self, doomed: set):
		"""`frappe.delete_doc` that raises for the names in `doomed`; the order of calls goes in `self.calls`."""
		self.calls = []

		def delete(doctype, name=None, *args, **kwargs):
			self.calls.append((doctype, name))
			if name in doomed:
				raise RuntimeError(f"cannot delete {name} for Marisol Vega m.vega@example.com")
			return REAL_DELETE(doctype, name, *args, **kwargs)

		return patch("frappe.delete_doc", side_effect=delete)

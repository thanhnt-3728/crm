# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Error Log is a MyISAM table, so its rows outlive a test's rollback. A test that makes the code under test log an
error watches the table, reads only the rows that are new, and removes exactly those by name when it is done."""

import frappe

DOCTYPE = "CRM Erasure Request"


class ErrorLogWatch:
	"""Mixin for a TestCase: call `watch_error_logs()` in `setUp`."""

	def watch_error_logs(self) -> None:
		self._known_logs = set(self._logs_about_requests())
		self.addCleanup(self._remove_new_logs)

	@staticmethod
	def _logs_about_requests() -> list[str]:
		about = frappe.get_all("Error Log", {"reference_doctype": DOCTYPE}, pluck="name")
		return about + frappe.get_all("Error Log", {"method": "Retained contract purge"}, pluck="name")

	def _new_names(self) -> list[str]:
		return [name for name in self._logs_about_requests() if name not in self._known_logs]

	def new_logs(self, **filters) -> list:
		"""The Error Log rows this test caused, with `method` and `error`, narrowed by `filters`."""
		names = self._new_names()
		if not names:
			return []
		return frappe.get_all(
			"Error Log", {"name": ["in", names], **filters}, ["name", "method", "error", "reference_name"]
		)

	def _remove_new_logs(self) -> None:
		names = self._new_names()
		if names:
			frappe.db.delete("Error Log", {"name": ["in", names]})
			frappe.db.commit()  # nosemgrep

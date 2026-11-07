# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The whole request lifecycle in one test case (phase 08): the Marisol scenario is already logged, submitted, held,
released and rechecked by `ErasureTestCase`; this adds approve + job (`approve_and_run`) and then close.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from crm.api.erasure_review import close_request, set_checklist_item_done
from crm.privacy.tests.erasure_run_case import DOCTYPE, ExecutorCase
from crm.privacy.tests.leak_sweep_scan import search_keys
from crm.privacy.tests.make_test_user import as_user


class LifecycleCase(ExecutorCase):
	"""Closing flushes the search queue, and `__global_search` is MyISAM: the rows of the fixture's emails outlive the
	rollback. `self.old_search_rows` is what was there before the fixture; the rows added after it are removed, each
	by its exact key, when the test ends."""

	def setUp(self):
		self.old_search_rows = search_keys()
		self.addCleanup(self.forget_new_search_rows)
		super().setUp()

	def forget_new_search_rows(self):
		for doctype, name in search_keys() - self.old_search_rows:
			frappe.db.sql(
				"delete from `__global_search` where `doctype` = %s and `name` = %s", (doctype, name)
			)

	def tick_checklist(self) -> int:
		"""Compliance ticks every open item (the Twilio and Data Import ones the job added). Returns how many."""
		open_rows = [row.name for row in frappe.get_doc(DOCTYPE, self.request).checklist if not row.done]
		for row in open_rows:
			as_user(self.compliance, set_checklist_item_done, self.request, row, True)
		return len(open_rows)

	def close_and_finish(self) -> dict:
		"""Close as Compliance, then run what close queued for after the commit, without committing the fixture."""
		self.tick_checklist()
		closed = as_user(self.compliance, close_request, self.request, today(), "Completed", None)
		with patch("frappe.db.commit"):
			frappe.db.after_commit.run()
		return closed

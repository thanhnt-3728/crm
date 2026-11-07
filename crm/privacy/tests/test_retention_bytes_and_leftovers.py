# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fix round 1 for the purge (C1, H2, M3, L1, L2): search rows and comments of leftovers, a byte deletion that
never works, an empty contract request, and the order of the daily steps."""

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, global_search, today

from crm.privacy import retention
from crm.privacy.tests.erasure_fixture_files import file_doc
from crm.privacy.tests.inbound_helpers import incoming_email
from crm.privacy.tests.retention_case import CONTRACT, DOCTYPE, RetentionCase

BYTES = "crm.privacy.erasure.file_bytes.delete_bytes"
PENDING = json.dumps([["/files/stuck-marisol-vega.txt", 0]])


class TestLeftoversAtPurge(RetentionCase):
	def setUp(self):
		super().setUp()
		self.request = self.closed()
		self.mail = incoming_email("someone@example.org", None, subject="Left over", content="x")
		self.mail.reference_doctype, self.mail.reference_name = DOCTYPE, self.request
		self.mail.insert(ignore_permissions=True)
		self.comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Attachment",
				"reference_doctype": "Communication",
				"reference_name": self.mail.name,
				"content": "added marisol-passport.pdf",
			}
		).insert(ignore_permissions=True)
		self.file = file_doc(DOCTYPE, self.request, "marisol-vega-id.txt")
		self.addCleanup(self.drop_search_rows)
		global_search.sync_global_search()

	def drop_search_rows(self) -> None:
		global_search.sync_global_search()
		frappe.db.sql("delete from __global_search where name = %s", (self.file.name,))

	def file_rows(self) -> int:
		return len(frappe.db.sql("select name from __global_search where name = %s", (self.file.name,)))

	def after_commit(self) -> None:
		with patch("frappe.db.commit"):
			frappe.db.after_commit.run()

	def test_comments_on_a_leftover_email_are_deleted_before_the_request(self):
		self.run_job()
		self.assertFalse(self.exists(self.request))
		self.assertFalse(frappe.db.exists("Comment", self.comment.name))

	def test_the_search_row_of_a_deleted_file_goes_after_the_commit_and_not_before(self):
		self.assertEqual(self.file_rows(), 1)
		self.run_job()
		self.assertEqual(self.file_rows(), 1, "MyISAM cannot roll back: nothing is deleted before the commit")
		self.after_commit()
		self.assertEqual(self.file_rows(), 0)

	def test_a_failed_purge_keeps_the_search_row(self):
		with self.failing_delete({self.request}):
			self.run_job()
		self.after_commit()
		self.assertEqual(self.file_rows(), 1)


class TestAByteDeletionThatNeverWorks(RetentionCase):
	"""M3: after `MAX_BYTE_DELETE_FAILURES` daily failures the purge goes ahead and the path is left for a person."""

	def setUp(self):
		super().setUp()
		self.request = self.closed(pending_file_deletions=PENDING)

	def run_failing(self):
		with patch(BYTES, side_effect=OSError("cannot remove marisol-vega.pdf")):
			self.run_job()

	def notices(self) -> list:
		return frappe.get_all(
			"CRM Notification",
			{"to_user": self.compliance, "type": "Compliance", "message": ["like", f"%{self.request}%"]},
			pluck="message",
		)

	def test_the_request_waits_until_the_cap_is_reached(self):
		for attempt in range(1, retention.MAX_BYTE_DELETE_FAILURES):
			self.run_failing()
			self.assertTrue(self.exists(self.request), f"attempt {attempt}")
		self.assertEqual(self.notices(), [])
		logs = self.new_logs()
		self.assertEqual(len(logs), retention.MAX_BYTE_DELETE_FAILURES - 1)
		for log in logs:
			self.assertEqual(log.method, self.request)
			self.assertTrue(log.error.startswith("OSError"))
			self.assertNotIn("marisol", log.error.lower())

	def test_at_the_cap_the_request_is_purged_compliance_is_told_once_and_the_path_is_recorded(self):
		for _ in range(retention.MAX_BYTE_DELETE_FAILURES - 1):
			self.run_failing()
		with patch("frappe.logger") as logger:
			self.run_failing()
		self.assertFalse(self.exists(self.request))
		notices = self.notices()
		self.assertEqual(len(notices), 1)
		self.assertNotIn("marisol", notices[0].lower())
		logger.assert_any_call("erasure_cleanup", allow_site=True)
		written = " ".join(str(c) for c in logger.return_value.info.call_args_list)
		self.assertIn("/files/stuck-marisol-vega.txt", written)
		self.assertIn(self.request, written)
		self.run_failing()
		self.assertEqual(len(self.notices()), 1)

	def test_a_run_that_works_purges_at_once(self):
		self.run_job()
		self.assertFalse(self.exists(self.request))
		self.assertEqual(self.notices(), [])


class TestOrderAndEmptyRequest(RetentionCase):
	def test_a_contract_without_a_request_is_never_logged_against_another_request(self):
		other = self.closed(add_days(today(), 30))  # exists, not due: the row a lookup of None would return
		bad = self.contract()
		with self.failing_delete({bad}):
			self.run_job()
		logs = self.new_logs(method="Retained contract purge")
		self.assertEqual([(log.error, log.reference_name) for log in logs], [("RuntimeError", None)])
		self.assertFalse(
			frappe.db.exists("Error Log", {"reference_name": other, "reference_doctype": DOCTYPE})
		)
		self.assertTrue(frappe.db.exists(CONTRACT, bad))

	def test_a_failure_in_the_byte_sweep_comes_after_both_purge_loops(self):
		request, contract = self.closed(), self.contract()
		with patch.object(retention, "finish_closed_file_deletions", side_effect=RuntimeError("x")):
			with self.assertRaises(RuntimeError):
				self.run_job()
		self.assertFalse(frappe.db.exists(CONTRACT, contract))
		self.assertFalse(self.exists(request))

	def test_an_empty_request_is_not_looked_up_at_all(self):
		"""Some Frappe versions answer `exists(doctype, None)` with the first row: the code must not ask."""
		bad = self.contract()
		asked = []
		real = frappe.db.exists

		def exists(doctype, name=None, *args, **kwargs):
			asked.append((doctype, name))
			return real(doctype, name, *args, **kwargs)

		with patch.object(frappe.db, "exists", side_effect=exists), self.failing_delete({bad}):
			self.run_job()
		self.assertNotIn((DOCTYPE, None), asked)
		self.assertNotIn((DOCTYPE, ""), asked)

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What still points at a request must not stop its purge, and one failure must not stop the run (RT-12, V1)."""

import os
from unittest.mock import patch

import frappe

from crm.privacy.tests.erasure_fixture_files import file_doc
from crm.privacy.tests.inbound_helpers import incoming_email
from crm.privacy.tests.retention_case import CONTRACT, DOCTYPE, RetentionCase


class TestLinkedRows(RetentionCase):
	"""RT-12: whatever still points at the request must not make the purge fail."""

	def setUp(self):
		super().setUp()
		self.request = self.closed()
		self.mail = incoming_email("someone@example.org", None, subject="Left over", content="Keep the row")
		self.mail.reference_doctype, self.mail.reference_name = DOCTYPE, self.request
		self.mail.insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Communication Link", "parenttype": "Communication", "parent": self.mail.name,
			"parentfield": "timeline_links", "link_doctype": DOCTYPE, "link_name": self.request}).db_insert()  # fmt: skip
		self.comment = frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": DOCTYPE,
			"reference_name": self.request, "content": "note"}).insert(ignore_permissions=True)  # fmt: skip
		self.notice = frappe.get_doc({"doctype": "CRM Notification", "type": "Compliance", "to_user": self.compliance,
			"notification_type_doctype": DOCTYPE, "notification_type_doc": self.request, "reference_doctype": DOCTYPE,
			"reference_name": self.request, "message": self.request}).insert(ignore_permissions=True)  # fmt: skip
		self.file = file_doc(DOCTYPE, self.request, "left-over.txt")

	def test_the_request_is_purged_and_the_email_stays_unlinked(self):
		self.run_job()
		self.assertFalse(self.exists(self.request))
		row = frappe.db.get_value("Communication", self.mail.name, ["reference_doctype", "reference_name"])
		self.assertEqual(tuple(row), (None, None))
		self.assertEqual(frappe.db.count("Communication Link", {"link_name": self.request}), 0)

	def test_comments_notifications_and_files_are_deleted(self):
		self.run_job()
		self.assertFalse(frappe.db.exists("Comment", self.comment.name))
		self.assertFalse(frappe.db.exists("CRM Notification", self.notice.name))
		self.assertFalse(frappe.db.exists("File", self.file.name))

	def test_leftover_file_bytes_go_after_the_commit(self):
		self.run_job()
		self.assertTrue(os.path.exists(self.file.get_full_path()), "bytes must outlive the transaction")
		with patch("frappe.db.commit"):
			frappe.db.after_commit.run()
		self.assertFalse(os.path.exists(self.file.get_full_path()))

	def test_a_request_that_fails_to_delete_keeps_every_link_it_had(self):
		with self.failing_delete({self.request}):
			self.run_job()
		self.assertTrue(self.exists(self.request))
		self.assertTrue(frappe.db.exists("Comment", self.comment.name))
		self.assertTrue(frappe.db.exists("CRM Notification", self.notice.name))
		self.assertTrue(frappe.db.exists("File", self.file.name))
		self.assertEqual(frappe.db.get_value("Communication", self.mail.name, "reference_name"), self.request)
		with patch("frappe.db.commit"):
			frappe.db.after_commit.run()
		self.assertTrue(
			os.path.exists(self.file.get_full_path()), "a rolled back purge must not delete bytes"
		)


class TestIsolation(RetentionCase):
	def test_a_request_that_fails_is_logged_and_the_rest_of_the_run_goes_on(self):
		bad, good = self.closed(), self.closed()
		contract = self.contract()
		queued = len(frappe.local.message_log)
		with self.failing_delete({bad}):
			self.run_job()
		self.assertTrue(self.exists(bad))
		self.assertFalse(self.exists(good))
		self.assertFalse(frappe.db.exists(CONTRACT, contract))
		self.assertEqual(len(frappe.local.message_log), queued)
		self.assertEqual([(log.method, log.error) for log in self.new_logs()], [(bad, "RuntimeError")])

	def test_retained_contracts_are_purged_before_requests(self):
		self.closed()
		self.contract()
		with self.failing_delete(set()):
			self.run_job()
		kinds = [doctype for doctype, _ in self.calls]
		self.assertEqual(kinds, [CONTRACT, DOCTYPE])

	def test_a_contract_that_fails_does_not_stop_the_others_or_the_requests(self):
		request = self.closed()
		bad, good = self.contract(request=request), self.contract()
		with self.failing_delete({bad}):
			self.run_job()
		self.assertTrue(frappe.db.exists(CONTRACT, bad))
		self.assertFalse(frappe.db.exists(CONTRACT, good))
		self.assertFalse(self.exists(request))
		self.assertEqual([(log.method, log.error) for log in self.new_logs()], [(request, "RuntimeError")])

	def test_an_unexpected_failure_while_listing_never_hides_the_other_loop(self):
		self.closed()
		contract = self.contract()
		with patch("crm.privacy.retention.purge_requests", side_effect=RuntimeError("x")):
			with self.assertRaises(RuntimeError):
				self.run_job()
		self.assertFalse(frappe.db.exists(CONTRACT, contract))

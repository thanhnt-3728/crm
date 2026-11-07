# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The daily purge of closed requests and retained contracts (phase 06 step 4; design 5.8, 5.11)."""

import json
import os
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from crm.privacy.tests.erasure_fixture_files import file_doc
from crm.privacy.tests.make_test_user import block, make_request
from crm.privacy.tests.retention_case import CONTRACT, DOCTYPE, RetentionCase, deleted_copies


class TestClosedRequests(RetentionCase):
	def test_a_request_due_today_is_deleted_without_a_deleted_document_copy(self):
		name = self.closed()
		self.run_job()
		self.assertFalse(self.exists(name))
		self.assertEqual(deleted_copies(DOCTYPE, name), 0)

	def test_the_boundary_days(self):
		yesterday = self.closed(add_days(today(), -1))
		due = self.closed(today())
		tomorrow = self.closed(add_days(today(), 1))
		self.run_job()
		self.assertEqual([self.exists(n) for n in (yesterday, due, tomorrow)], [False, False, True])

	def test_today_can_be_passed(self):
		name = self.closed(add_days(today(), 10))
		self.run_job(add_days(getdate(), 10))
		self.assertFalse(self.exists(name))

	def test_a_request_that_is_not_closed_is_never_purged(self):
		names = [
			self.closed(add_days(today(), -30), status=s) for s in ("Erased", "Declined", "Awaiting sign-off")
		]
		self.run_job()
		self.assertTrue(all(self.exists(n) for n in names))

	def test_do_not_contact_entries_survive(self):
		block(("email", "m.vega@example.com"), ("phone", "+15305550101"))
		before = frappe.db.count("CRM Do Not Contact")
		self.closed()
		self.run_job()
		self.assertEqual(frappe.db.count("CRM Do Not Contact"), before)
		self.assertGreaterEqual(before, 2)

	def test_a_second_run_changes_nothing(self):
		kept = self.closed(add_days(today(), 5))
		self.closed()
		self.run_job()
		self.run_job()
		self.assertTrue(self.exists(kept))
		self.assertEqual(self.new_logs(), [])


class TestRetainedContracts(RetentionCase):
	def test_due_today_is_deleted_permanently_and_tomorrow_is_kept(self):
		due, later = self.contract(today()), self.contract(add_days(today(), 1))
		self.run_job()
		self.assertFalse(frappe.db.exists(CONTRACT, due))
		self.assertEqual(deleted_copies(CONTRACT, due), 0)
		self.assertTrue(frappe.db.exists(CONTRACT, later))

	def test_the_boundary_days(self):
		yesterday, due, tomorrow = (self.contract(add_days(today(), d)) for d in (-1, 0, 1))
		self.run_job()
		self.assertEqual(
			[bool(frappe.db.exists(CONTRACT, n)) for n in (yesterday, due, tomorrow)], [False, False, True]
		)


class TestFileBytesLeftOnClosedRequests(RetentionCase):
	def test_the_run_finishes_what_a_close_could_not(self):
		doc = file_doc(DOCTYPE, make_request(self.logger), "left-by-close.txt")
		path = doc.get_full_path()
		frappe.db.delete("File", {"name": doc.name})
		request = self.closed(add_days(today(), 100), pending_file_deletions=json.dumps([[doc.file_url, 1]]))
		with patch("frappe.db.commit"):
			self.run_job()
		self.assertFalse(os.path.exists(path))
		self.assertFalse(frappe.db.get_value(DOCTYPE, request, "pending_file_deletions"))
		self.assertTrue(self.exists(request))

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""All or nothing: a failure anywhere rolls everything back, renames and file rows included (phase 05 step 12)."""

import os
from unittest.mock import patch

import frappe

from crm.privacy.erasure import scrub_names
from crm.privacy.tests.erasure_run_case import ExecutorCase, snapshot

SECRET_BITS = ("Marisol", "Vega", "m.vega", "5305550101", "boom")


class FailureCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.approve()
		self.before = snapshot()
		self.messages = len(frappe.local.message_log)
		h = self.activity.history
		self.paths = [frappe.get_doc("File", n).get_full_path() for n in (h.photo, h.file_lead, h.file_won)]

	def fail_with(self, target, **patch_args):
		patch_args.setdefault("side_effect", RuntimeError("boom Marisol Vega m.vega@example.com 5305550101"))
		with patch(target, **patch_args):
			self.run_job()

	def assertNothingChanged(self):
		self.assertEqual(snapshot(), self.before)
		self.assertTrue(all(os.path.exists(path) for path in self.paths))
		stored = self.stored("status", "erasure_job_status", "erasure_error", "approver", "approved_plan_hash",
			"pending_file_deletions", "approved_on")  # fmt: skip
		self.assertEqual(stored.status, "Awaiting sign-off")
		self.assertEqual(stored.erasure_job_status, "Failed")
		self.assertTrue(stored.erasure_error)
		self.assertFalse(stored.approver or stored.approved_plan_hash or stored.approved_on)
		self.assertFalse(stored.pending_file_deletions)
		for bit in SECRET_BITS:
			self.assertNotIn(bit, stored.erasure_error)
		self.assertFalse(frappe.flags.in_erasure)


class TestRollback(FailureCase):
	def test_a_failure_in_the_misc_step_changes_nothing(self):
		self.fail_with("crm.privacy.erasure.executor.scrub_misc.scrub")
		self.assertNothingChanged()

	def test_a_failure_in_the_rename_step_undoes_the_first_rename_too(self):
		real = scrub_names.rename_to_placeholder
		calls = []

		def second_one_fails(*args, **kwargs):
			calls.append(args)
			if len(calls) == 2:
				raise RuntimeError("boom")
			return real(*args, **kwargs)

		self.fail_with("crm.privacy.erasure.scrub_names.rename_to_placeholder", side_effect=second_one_fails)
		self.assertEqual(len(calls), 2)
		self.assertTrue(frappe.db.exists("Contact", self.p.contact))
		self.assertTrue(frappe.db.exists("Address", self.p.address))
		self.assertNothingChanged()

	def test_a_failure_after_the_file_rows_were_deleted_keeps_rows_and_bytes(self):
		self.fail_with("crm.privacy.erasure.executor.scrub_history.scrub")
		self.assertEqual(frappe.db.count("File", {"name": ["in", [self.activity.history.file_lead]]}), 1)
		self.assertNothingChanged()

	def test_a_failure_while_blocking_the_identifiers_changes_nothing(self):
		self.fail_with("crm.privacy.erasure.executor.add_entries")
		self.assertEqual(frappe.db.count("CRM Do Not Contact"), 0)
		self.assertNothingChanged()

	def test_a_failure_in_the_first_step_changes_nothing(self):
		self.fail_with("crm.privacy.erasure.executor.scrub_records.scrub")
		self.assertNothingChanged()


class TestWhatTheFailureSays(FailureCase):
	def test_the_log_holds_the_request_number_and_the_exception_class_only(self):
		self.fail_with("crm.privacy.erasure.executor.scrub_misc.scrub")
		logs = frappe.get_all("Error Log", {"reference_name": self.request}, ["method", "error"])
		self.assertEqual([(log.method, log.error) for log in logs], [(self.request, "RuntimeError")])

	def test_the_users_message_queue_is_left_as_it_was(self):
		def noisy(*args, **kwargs):
			frappe.msgprint("Marisol Vega m.vega@example.com")
			frappe.throw("Marisol Vega again")

		self.fail_with("crm.privacy.erasure.executor.scrub_misc.scrub", side_effect=noisy)
		self.assertEqual(len(frappe.local.message_log), self.messages)

	def test_compliance_can_approve_again_and_the_job_then_succeeds(self):
		self.fail_with("crm.privacy.erasure.executor.scrub_misc.scrub")
		self.approve()
		self.assertEqual(self.stored("erasure_job_status").erasure_job_status, "Queued")
		self.run_job()
		self.assertEqual(self.stored("status").status, "Erased")
		self.assertFalse(os.path.exists(self.paths[0]))

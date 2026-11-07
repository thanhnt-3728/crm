# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Closing a request (phase 06 step 3; design 5.2, 5.8; RT-8, RT-12): who may, what is required, what is wiped."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, getdate, today

from crm.privacy.tests.close_fixture import EMAIL, CloseTestCase, add_rows, force_request, holds_her_values

KEPT = ("date_received", "request_type", "channel", "logged_by", "acknowledge_by", "respond_by")
FIELDS = ("status", "closed_on", "purge_after", "outcome", "date_answered", "denial_reason")


class TestWhoMayClose(CloseTestCase):
	def assertRefused(self, user, error=frappe.PermissionError):
		before = self.stored(*FIELDS, "requester_names")
		with self.assertRaises(error):
			self.close(user)
		self.assertEqual(self.stored(*FIELDS, "requester_names"), before)
		self.assertTrue(
			frappe.db.exists("Communication", {"name": self.mail, "reference_name": self.request})
		)

	def test_a_sales_user_cannot(self):
		self.assertRefused(self.other)

	def test_a_sales_manager_cannot(self):
		self.assertRefused(self.manager)

	def test_the_logger_cannot(self):
		self.assertRefused(self.logger)

	def test_administrator_without_an_explicit_compliance_row_cannot(self):
		self.assertEqual(frappe.db.count("Has Role", {"parent": "Administrator", "role": "Compliance"}), 0)
		self.assertRefused("Administrator")

	def test_compliance_can(self):
		self.assertEqual(self.close()["status"], "Closed")


class TestCloseRules(CloseTestCase):
	def assertRefused(self, error=frappe.ValidationError, **kwargs):
		before = self.stored(*FIELDS, "requester_names")
		with self.assertRaises(error):
			self.close(**kwargs)
		self.assertEqual(self.stored(*FIELDS, "requester_names"), before)
		self.assertEqual(frappe.db.count("File", {"name": self.file.name}), 1)

	def test_an_open_checklist_item_blocks(self):
		add_rows(self.request, "checklist", [self.item("Check Data Import files", 0)])
		self.assertRefused()

	def test_a_denial_reason_is_required_for_denied_and_partly_completed(self):
		force_request(self.request, status="Declined")
		for reason in (None, "", "   "):
			with self.subTest(reason=reason):
				self.assertRefused(outcome="Denied", reason=reason)
		force_request(self.request, status="Erased")
		for reason in (None, "  "):
			with self.subTest(partly=reason):
				self.assertRefused(outcome="Partly completed", reason=reason)

	def test_completed_needs_no_reason_and_stores_none(self):
		self.close(reason="not needed")
		self.assertIsNone(self.stored("denial_reason").denial_reason)

	def test_a_declined_request_must_close_as_denied(self):
		force_request(self.request, status="Declined", denial_reason="Identity not verifiable")
		self.assertRefused(outcome="Completed")

	def test_a_declined_request_closes_with_the_reason_it_was_declined_with(self):
		force_request(self.request, status="Declined", denial_reason="Identity not verifiable")
		self.close(outcome="Denied")
		self.assertEqual(self.stored("denial_reason", "outcome").outcome, "Denied")
		self.assertEqual(self.stored("denial_reason").denial_reason, "Identity not verifiable")

	def test_an_erased_request_cannot_close_as_denied(self):
		self.assertRefused(outcome="Denied", reason="because")

	def test_partly_completed_with_a_reason_closes(self):
		self.close(outcome="Partly completed", reason="Signed contract kept")
		self.assertEqual(self.stored("outcome", "denial_reason").denial_reason, "Signed contract kept")

	def test_the_outcome_must_be_one_of_the_three(self):
		for outcome in (None, "", "Done", "completed"):
			with self.subTest(outcome=outcome):
				self.assertRefused(outcome=outcome)

	def test_date_answered_is_required_and_between_received_and_today(self):
		received = getdate(self.stored("date_received").date_received)
		for answered, label in ((None, "none"), ("", "empty"), ("nonsense", "garbage"),
				(add_days(received, -1), "before received"), (add_days(today(), 1), "future")):  # fmt: skip
			with self.subTest(label):
				with self.assertRaises(frappe.ValidationError):
					self.close(answered=answered)
		self.assertEqual(self.stored("status").status, "Erased")

	def test_the_boundary_dates_are_accepted(self):
		for answered in (self.stored("date_received").date_received, today()):
			with self.subTest(answered=answered):
				force_request(self.request, status="Erased")
				self.assertEqual(self.close(answered=answered)["status"], "Closed")
				self.finish_after_commit()

	def test_only_an_erased_or_declined_request_closes(self):
		for status in ("Logged", "Awaiting sign-off", "On Hold", "Closed"):
			with self.subTest(status=status):
				force_request(self.request, status=status)
				self.assertRefused()

	def test_a_running_job_refuses(self):
		for job in ("Queued", "Running"):
			with self.subTest(job=job):
				force_request(self.request, erasure_job_status=job)
				self.assertRefused()

	def test_close_is_refused_while_file_bytes_are_still_pending(self):
		force_request(self.request, pending_file_deletions='[["/files/x.txt", 0]]')
		self.assertRefused()

	def test_closing_twice_is_refused(self):
		self.close()
		with self.assertRaises(frappe.ValidationError):
			self.close()


class TestWhatClosingWipes(CloseTestCase):
	def test_the_log_entry_stays_and_the_dates_are_set(self):
		before = self.stored(*KEPT)
		self.close()
		after = self.stored(*KEPT, *FIELDS)
		for field in KEPT:
			self.assertEqual(after[field], before[field], field)
		self.assertEqual((after.status, after.outcome), ("Closed", "Completed"))
		self.assertEqual(getdate(after.closed_on), getdate(today()))
		self.assertEqual(getdate(after.purge_after), add_months(getdate(today()), 24))
		self.assertEqual(getdate(after.date_answered), getdate(today()))

	def test_names_message_and_every_child_row_are_wiped(self):
		self.assertTrue(holds_her_values(self.request))
		self.close()
		doc = frappe.get_doc("CRM Erasure Request", self.request)
		self.assertFalse(doc.requester_names or doc.original_message)
		for table in ("identifiers", "matches", "checklist", "contract_references"):
			self.assertEqual(doc.get(table), [], table)
		self.finish_after_commit()  # until then the file names wait on the request, to find the bytes
		self.assertEqual(holds_her_values(self.request), [])

	def test_the_response_is_the_closed_request_with_no_actions_left(self):
		result = self.close()
		self.assertEqual(result["status"], "Closed")
		self.assertFalse(any(result["can"].values()))
		self.assertEqual(result["identifiers"], [])

	def test_a_finished_request_stays_immutable_afterwards(self):
		self.close()
		doc = frappe.get_doc("CRM Erasure Request", self.request)
		doc.channel = "Phone"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_do_not_contact_entries_are_not_touched(self):
		from crm.privacy.tests.make_test_user import block

		block(("email", EMAIL))
		before = frappe.db.count("CRM Do Not Contact")
		self.close()
		self.assertEqual(frappe.db.count("CRM Do Not Contact"), before)


class TestAtomic(CloseTestCase):
	def test_a_failure_part_way_changes_nothing_and_queues_no_byte_deletion(self):
		self.assertEqual(self.byte_deletions_queued(), 0)
		frappe.db.savepoint("before_close")
		queued = self.byte_deletions_queued()
		with patch("crm.privacy.request_close.wipe_request", side_effect=RuntimeError("x")):
			with self.assertRaises(RuntimeError):
				self.close()
		frappe.db.rollback(save_point="before_close")
		self.assertEqual(self.byte_deletions_queued(), queued)
		self.assertEqual(self.stored("status", "requester_names").status, "Erased")
		self.assertEqual(frappe.db.get_value("Communication", self.mail, "reference_name"), self.request)
		self.assertTrue(frappe.db.exists("File", self.file.name))
		self.assertTrue(self.bytes_exist(self.file))

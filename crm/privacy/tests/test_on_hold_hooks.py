# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Hooks on deal and contact saves and deletes never break the user's own write, and never show them an error
(RT-11, V1, M1, M2). A hook runs one cheap lookup and queues a deduplicated per-request job after the commit."""

from unittest.mock import patch

import frappe

from crm.privacy.on_hold import recheck_request
from crm.privacy.tests.make_test_user import force_request, make_deal
from crm.privacy.tests.test_on_hold import CONTACT, DEAL, PERSONAL, OnHoldCase, notices

RECHECK = "crm.privacy.on_hold.recheck_request"
LEAK = "PDR-0001 m.vega@example.com 5305550101"


def recheck_calls(enqueue):
	return [c for c in enqueue.call_args_list if (c.args[:1] or [None])[0] == RECHECK]


class HookCase(OnHoldCase):
	def setUp(self):
		super().setUp()
		self.submit()

	def save_deal(self, **changes):
		deal = frappe.get_doc(DEAL, self.person.negotiation)
		deal.update(changes or {"status": "Won"})
		deal.save()

	def error_logs(self):
		return frappe.get_all(
			"Error Log", filters={"reference_name": self.name}, fields=["method", "error", "reference_name"]
		)


class TestTheHookOnlyQueuesAJob(HookCase):
	def test_a_deal_save_queues_one_deduplicated_job_after_the_commit(self):
		with patch("frappe.enqueue") as enqueue, patch("crm.privacy.on_hold.evaluate_hold") as evaluate:
			self.save_deal()
		evaluate.assert_not_called()
		(call,) = recheck_calls(enqueue)
		self.assertEqual(call.kwargs["request"], self.name)
		self.assertEqual(call.kwargs["job_id"], f"erasure-hold-recheck::{self.name}")
		self.assertIs(call.kwargs["deduplicate"], True)
		self.assertIs(call.kwargs["enqueue_after_commit"], True)

	def test_the_hook_does_not_touch_the_request(self):
		before = self.stored()
		with patch("frappe.enqueue"):
			self.save_deal()
		after = self.stored()
		self.assertEqual((after.status, after.modified), (before.status, before.modified))
		self.assertEqual(len(after.matches), len(before.matches))

	def test_a_deleted_deal_and_a_deleted_contact_queue_the_job_too(self):
		with patch("frappe.enqueue") as enqueue:
			frappe.delete_doc(DEAL, self.person.negotiation, force=True)
			frappe.delete_doc(CONTACT, self.person.contact, force=True)
		self.assertEqual([c.kwargs["request"] for c in recheck_calls(enqueue)], [self.name, self.name])

	def test_nothing_is_queued_for_a_deal_that_is_on_no_row(self):
		other = make_deal([], status="Negotiation")
		deal = frappe.get_doc(DEAL, other)
		deal.status = "Won"
		with patch("frappe.enqueue") as enqueue:
			deal.save()
		self.assertEqual(recheck_calls(enqueue), [])

	def test_nothing_is_looked_up_when_no_request_is_on_hold(self):
		force_request(self.name, status="Awaiting sign-off")
		with patch("frappe.enqueue") as enqueue, patch("crm.privacy.on_hold.requests_holding") as lookup:
			self.save_deal()
		lookup.assert_not_called()
		self.assertEqual(recheck_calls(enqueue), [])


class TestTheJob(HookCase):
	def test_running_it_twice_changes_nothing_the_second_time(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		recheck_request(self.name)
		first = self.stored()
		recheck_request(self.name)
		second = self.stored()
		self.assertEqual((second.status, second.modified), ("Awaiting sign-off", first.modified))
		self.assertEqual(len(notices(self.compliance, reference_name=self.name)), 1)

	def test_it_loads_the_request_fresh_so_a_stale_queue_entry_is_harmless(self):
		recheck_request(self.name)  # nothing changed: still held
		self.assertEqual(self.stored().status, "On Hold")
		force_request(self.name, status="Declined", denial_reason="x")
		recheck_request(self.name)  # no longer On Hold: left alone
		self.assertEqual(self.stored().status, "Declined")

	def test_a_failure_is_logged_with_the_pdr_number_and_class_only_and_not_raised(self):
		with patch("crm.privacy.on_hold.evaluate_hold", side_effect=RuntimeError(LEAK)):
			recheck_request(self.name)
		(entry,) = self.error_logs()
		self.assertEqual((entry.method, entry.error), (self.name, "RuntimeError"))
		for fragment in PERSONAL:
			self.assertNotIn(fragment, entry.method + entry.error)

	def test_a_half_written_run_is_rolled_back(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")

		def write_then_fail(doc, **kwargs):
			frappe.db.set_value("CRM Erasure Request", doc.name, "status", "Awaiting sign-off")
			raise RuntimeError("late")

		with patch("crm.privacy.on_hold.evaluate_hold", write_then_fail):
			recheck_request(self.name)
		self.assertEqual(self.stored().status, "On Hold")
		self.assertEqual(frappe.db.get_value(DEAL, self.person.negotiation, "status"), "Won")


class TestNoErrorReachesTheUser(HookCase):
	def thrower(self, *args, **kwargs):
		frappe.throw(LEAK)

	def test_a_message_raised_inside_the_job_is_not_left_for_the_user(self):
		before = list(frappe.local.message_log)
		with patch("crm.privacy.on_hold.evaluate_hold", self.thrower):
			recheck_request(self.name)
		self.assertEqual(frappe.local.message_log, before)

	def test_a_failure_in_the_lookup_does_not_block_the_save_or_leave_a_message(self):
		before = list(frappe.local.message_log)
		with patch("frappe.enqueue"), patch("crm.privacy.on_hold.requests_holding", self.thrower):
			self.save_deal()
		self.assertEqual(frappe.db.get_value(DEAL, self.person.negotiation, "status"), "Won")
		self.assertEqual(frappe.local.message_log, before)

	def test_a_failure_to_queue_the_job_does_not_block_the_save_or_leave_a_message(self):
		before = list(frappe.local.message_log)
		with patch("frappe.enqueue", side_effect=ConnectionError(LEAK)):
			self.save_deal()
		self.assertEqual(frappe.db.get_value(DEAL, self.person.negotiation, "status"), "Won")
		self.assertEqual(frappe.local.message_log, before)
		filters = {"method": "CRM Deal hold re-check", "creation": [">=", self._started]}
		logs = frappe.get_all("Error Log", filters=filters, fields=["error"])
		self.assertEqual([entry.error for entry in logs], ["ConnectionError"])

	def test_a_failing_delete_hook_does_not_block_the_delete(self):
		def refuse_ours(method, *args, **kwargs):
			if method == RECHECK:
				raise ConnectionError(LEAK)

		with patch("frappe.enqueue", side_effect=refuse_ours):
			frappe.delete_doc(DEAL, self.person.negotiation, force=True)
		self.assertFalse(frappe.db.exists(DEAL, self.person.negotiation))

	def test_a_lookup_that_wrote_before_failing_is_rolled_back(self):
		def write_then_fail(*args, **kwargs):
			frappe.db.set_value("CRM Erasure Request", self.name, "status", "Awaiting sign-off")
			raise RuntimeError("late")

		with patch("frappe.enqueue"), patch("crm.privacy.on_hold.requests_holding", write_then_fail):
			self.save_deal()
		self.assertEqual(self.stored().status, "On Hold")
		self.assertEqual(frappe.db.get_value(DEAL, self.person.negotiation, "status"), "Won")

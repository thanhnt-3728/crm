# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the job checks before it touches anything: claim, approver, hold, plan hash, secret (RT-1, RT-2, RT-15)."""

from unittest.mock import patch

import frappe

from crm.privacy.tests.erasure_fixture_mail import mail
from crm.privacy.tests.erasure_run_case import ExecutorCase, savepoint_transactions, snapshot
from crm.privacy.tests.make_test_user import block, force_request, forget_dnc_secret, make_deal

PLAN_CHANGED = "Plan changed since approval; review and approve again"


class GuardCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.approve()

	def assertRefusedBeforeTouchingAnything(self, message=None, before=None):
		before = before or self.before
		self.assertEqual(snapshot(), before)
		stored = self.stored(
			"status", "erasure_job_status", "erasure_error", "approver", "approved_plan_hash"
		)
		self.assertEqual((stored.status, stored.erasure_job_status), ("Awaiting sign-off", "Failed"))
		if message:
			self.assertEqual(stored.erasure_error, message)
		self.assertFalse(stored.approver or stored.approved_plan_hash)

	def run_job(self):
		self.before = snapshot()
		super().run_job()


class TestClaim(GuardCase):
	def test_a_second_run_after_the_erasure_does_nothing(self):
		self.run_job()
		self.assertEqual(self.stored("status").status, "Erased")
		after = snapshot()
		with patch("crm.privacy.erasure.executor.scrub_records.scrub") as scrub:
			ExecutorCase.run_job(self)
		scrub.assert_not_called()
		self.assertEqual(snapshot(), after)
		self.assertEqual(list(self.stored("status", "erasure_job_status").values()), ["Erased", ""])

	def test_a_job_another_worker_already_claimed_is_left_alone(self):
		force_request(self.request, erasure_job_status="Running")
		with patch("crm.privacy.erasure.executor.scrub_records.scrub") as scrub:
			self.run_job()
		scrub.assert_not_called()
		self.assertEqual(
			list(self.stored("status", "erasure_job_status").values()), ["Awaiting sign-off", "Running"]
		)

	def test_a_request_that_is_no_longer_awaiting_sign_off_is_not_claimed(self):
		for status in ("Declined", "On Hold", "Logged"):
			force_request(self.request, status=status)
			with patch("crm.privacy.erasure.executor.scrub_records.scrub") as scrub:
				self.run_job()
			scrub.assert_not_called()
			self.assertEqual(self.stored("erasure_job_status").erasure_job_status, "Queued")

	def test_the_flag_is_set_while_the_job_runs_and_off_afterwards(self):
		seen = []
		with patch(
			"crm.privacy.erasure.executor.scrub_records.scrub",
			side_effect=lambda *a: seen.append(frappe.flags.in_erasure),
		):
			self.run_job()
		self.assertEqual(seen, [True])
		self.assertFalse(frappe.flags.in_erasure)


class TestApprover(GuardCase):
	def test_an_approver_who_lost_the_compliance_role_cannot_run_it(self):
		frappe.db.delete("Has Role", {"parent": self.compliance, "role": "Compliance"})
		self.run_job()
		self.assertRefusedBeforeTouchingAnything()

	def test_an_approver_who_is_the_logger_cannot_run_it(self):
		force_request(self.request, approver=self.manager)
		self.run_job()
		self.assertRefusedBeforeTouchingAnything()


class TestFrozenPlan(GuardCase):
	def test_a_match_edited_behind_the_api_fails_with_plan_changed(self):
		match = {"parent": self.request, "reference_name": self.p.contact}
		frappe.db.set_value("CRM Erasure Match", match, "confirmed", 0)
		self.run_job()
		self.assertRefusedBeforeTouchingAnything(PLAN_CHANGED)

	def test_a_new_email_from_her_fails_with_plan_changed(self):
		mail(self.p, self.p.email, subject="Me again", content="Please hurry")
		self.run_job()
		self.assertRefusedBeforeTouchingAnything(PLAN_CHANGED)

	def test_a_new_open_deal_with_her_contact_puts_the_request_on_hold(self):
		make_deal([self.p.contact], status="Negotiation")
		self.run_job()
		after = snapshot()
		for state in (after, self.before):  # the hold re-check adds the new deal's row to the matches
			state.pop("matches")
		self.assertEqual(after, self.before)
		stored = self.stored("status", "erasure_job_status", "approver", "approved_plan_hash", "approved_on")
		self.assertEqual(stored.status, "On Hold")
		self.assertFalse(
			stored.erasure_job_status or stored.approver or stored.approved_plan_hash or stored.approved_on
		)


class TestSecret(GuardCase):
	def test_a_lost_hash_secret_fails_the_job_before_anything_is_erased(self):
		with savepoint_transactions():
			block(("email", "someone.else@example.com"))
		forget_dnc_secret()
		self.run_job()
		self.assertRefusedBeforeTouchingAnything("Privacy settings are incomplete. Ask your administrator.")

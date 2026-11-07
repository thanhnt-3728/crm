# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Who may approve an erasure and what approval does (phase 05 step 3; RT-1, RT-2, design 5.6).

Approval enqueues the job and stops there: the executor is phase 05 part B, so `frappe.enqueue` is captured.
"""

from unittest.mock import patch

import frappe

from crm.api.erasure_review import approve_request
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.tests.erasure_fixture import ErasureTestCase
from crm.privacy.tests.make_test_user import as_user, force_request, make_deal, make_user

DOCTYPE = "CRM Erasure Request"
FIELDS = [
	"status",
	"approver",
	"approved_on",
	"erasure_job_status",
	"erasure_queued_at",
	"approved_plan_hash",
]


class ApprovalCase(ErasureTestCase):
	def setUp(self):
		super().setUp()
		self.manager2 = make_user("pdr.manager2@example.com", roles=["Sales Manager"])
		patcher = patch("frappe.enqueue")
		self.enqueue = patcher.start()
		self.addCleanup(patcher.stop)

	def approve(self, user, typed=None):
		return as_user(user, approve_request, self.request, typed or self.request)

	def stored(self):
		return frappe.db.get_value(DOCTYPE, self.request, FIELDS, as_dict=True)

	def assertRefused(self, user, error=frappe.ValidationError, typed=None):
		before = self.stored()
		with self.assertRaises(error):
			self.approve(user, typed)
		self.assertEqual(self.stored(), before)
		self.enqueue.assert_not_called()


class TestWhoMayApprove(ApprovalCase):
	def test_a_sales_user_cannot(self):
		self.assertRefused(self.other, frappe.PermissionError)

	def test_a_sales_manager_who_is_not_the_logger_cannot(self):
		self.assertRefused(self.manager2, frappe.PermissionError)

	def test_the_logger_without_compliance_cannot(self):
		self.assertRefused(self.manager, frappe.PermissionError)

	def test_the_logger_who_holds_compliance_cannot_approve_their_own_request(self):
		frappe.get_doc("User", self.manager).add_roles("Compliance")
		self.enqueue.reset_mock()  # saving the user queues its own jobs
		with self.assertRaisesRegex(frappe.PermissionError, "own"):
			self.approve(self.manager)
		self.assertFalse(self.stored().erasure_job_status)
		self.enqueue.assert_not_called()

	def test_administrator_without_an_explicit_compliance_row_cannot(self):
		self.assertEqual(frappe.db.count("Has Role", {"parent": "Administrator", "role": "Compliance"}), 0)
		self.assertRefused("Administrator", frappe.PermissionError)

	def test_compliance_who_did_not_log_it_can(self):
		self.approve(self.compliance)
		self.assertEqual(self.stored().approver, self.compliance)


class TestApprovalRules(ApprovalCase):
	def test_the_typed_number_must_be_exactly_the_request_number(self):
		for typed in ("", "pdr-0001", self.request + " x", "PDR-0002"):
			with self.subTest(typed=typed):
				before = self.stored()
				with self.assertRaises(frappe.ValidationError):
					as_user(self.compliance, approve_request, self.request, typed)
				self.assertEqual(self.stored(), before)

	def test_only_a_request_awaiting_sign_off_can_be_approved(self):
		for status in ("Logged", "On Hold", "Erased", "Declined", "Closed"):
			with self.subTest(status=status):
				force_request(self.request, status=status)
				self.assertRefused(self.compliance)

	def test_a_job_already_queued_or_running_refuses_a_second_approval(self):
		for job in ("Queued", "Running"):
			with self.subTest(job=job):
				force_request(self.request, erasure_job_status=job)
				self.assertRefused(self.compliance)

	def test_contract_references_need_a_retention_period(self):
		self.set_references(["CT-1001"])
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 0)
		self.assertRefused(self.compliance)
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 36)
		self.approve(self.compliance)
		self.assertEqual(self.stored().erasure_job_status, "Queued")

	def set_references(self, references):
		from crm.api.erasure_review import set_contract_references

		as_user(self.compliance, set_contract_references, self.request, references)


class TestOpenDealAtApproval(ApprovalCase):
	def test_a_new_open_deal_with_her_contact_puts_the_request_back_on_hold(self):
		make_deal([self.p.contact], status="Negotiation")
		result = self.approve(self.compliance)
		self.assertEqual(result["status"], "On Hold")
		self.assertEqual(self.stored().status, "On Hold")
		self.assertFalse(self.stored().erasure_job_status)
		self.assertFalse(self.stored().approved_plan_hash)
		self.assertFalse(self.stored().approver)
		self.enqueue.assert_not_called()

	def test_a_confirmed_open_deal_does_the_same(self):
		match = {"parent": self.request, "reference_name": self.p.removed}
		frappe.db.set_value("CRM Erasure Match", match, "confirmed", 1)
		result = self.approve(self.compliance)
		self.assertEqual(result["status"], "On Hold")
		self.assertFalse(self.stored().erasure_job_status)
		self.enqueue.assert_not_called()


class TestApproved(ApprovalCase):
	def test_the_job_is_enqueued_and_the_approval_recorded(self):
		self.approve(self.compliance)
		stored = self.stored()
		self.assertEqual(stored.status, "Awaiting sign-off")
		self.assertEqual(stored.erasure_job_status, "Queued")
		self.assertEqual(stored.approver, self.compliance)
		self.assertTrue(stored.approved_on and stored.erasure_queued_at)
		self.enqueue.assert_called_once_with(
			"crm.privacy.erasure.executor.run",
			queue="long",
			timeout=3600,
			job_id=f"erasure::{self.request}",
			deduplicate=True,
			enqueue_after_commit=True,
			request=self.request,
		)

	def test_the_stored_hash_is_the_hash_of_the_plan_at_approval(self):
		self.approve(self.compliance)
		plan = build_plan(frappe.get_doc(DOCTYPE, self.request))
		self.assertRegex(self.stored().approved_plan_hash, r"^[0-9a-f]{64}$")
		self.assertEqual(self.stored().approved_plan_hash, plan.hash())

	def test_the_request_is_frozen_afterwards(self):
		from crm.api.erasure_requests import update_request

		self.approve(self.compliance)
		with self.assertRaisesRegex(frappe.ValidationError, "Erasure in progress"):
			as_user(self.compliance, update_request, self.request, {"channel": "Phone"})

	def test_the_hash_is_not_returned_to_the_browser(self):
		result = self.approve(self.compliance)
		self.assertNotIn("approved_plan_hash", result)
		self.assertEqual(result["status"], "Awaiting sign-off")

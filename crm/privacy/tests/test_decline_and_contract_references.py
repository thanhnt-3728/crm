# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Declining a request and entering contract references (phase 05; RT-1, design 5.11)."""

import frappe

from crm.api.erasure_review import approve_request, decline_request, set_contract_references
from crm.privacy.tests.erasure_fixture import ErasureTestCase
from crm.privacy.tests.make_test_user import as_user, force_request, make_user

DOCTYPE = "CRM Erasure Request"
FINISHED = ("Erased", "Declined", "Closed")


class ReviewCase(ErasureTestCase):
	def setUp(self):
		super().setUp()
		self.manager2 = make_user("pdr.manager2@example.com", roles=["Sales Manager"])

	def row(self):
		fields = ["status", "denial_reason", "erasure_job_status"]
		return frappe.db.get_value(DOCTYPE, self.request, fields, as_dict=True)

	def references(self):
		filters = {"parent": self.request}
		return frappe.get_all("CRM Erasure Contract Reference", filters, pluck="reference", order_by="idx")

	def others(self):
		return (self.other, self.manager, self.manager2, "Administrator")


class TestDecline(ReviewCase):
	def test_compliance_declines_with_a_reason(self):
		result = as_user(self.compliance, decline_request, self.request, "  Not our customer  ")
		self.assertEqual(result["status"], "Declined")
		self.assertEqual(self.row().status, "Declined")
		self.assertEqual(self.row().denial_reason, "Not our customer")

	def test_a_reason_is_required(self):
		for reason in ("", "   "):
			with self.assertRaises(frappe.ValidationError):
				as_user(self.compliance, decline_request, self.request, reason)
		self.assertEqual(self.row().status, "Awaiting sign-off")

	def test_nobody_else_can_decline(self):
		for user in self.others():
			with self.assertRaises(frappe.PermissionError, msg=user):
				as_user(user, decline_request, self.request, "No")
		self.assertEqual(self.row().status, "Awaiting sign-off")

	def test_not_while_the_job_is_queued_or_running(self):
		for job in ("Queued", "Running"):
			force_request(self.request, erasure_job_status=job)
			with self.assertRaisesRegex(frappe.ValidationError, "Erasure in progress"):
				as_user(self.compliance, decline_request, self.request, "No")
		self.assertEqual(self.row().status, "Awaiting sign-off")

	def test_a_finished_request_cannot_be_declined(self):
		for status in FINISHED:
			force_request(self.request, status=status)
			with self.assertRaises(frappe.ValidationError, msg=status):
				as_user(self.compliance, decline_request, self.request, "No")
			self.assertEqual(self.row().status, status)

	def test_an_approved_request_cannot_be_declined(self):
		as_user(self.compliance, approve_request, self.request, self.request)
		with self.assertRaisesRegex(frappe.ValidationError, "Erasure in progress"):
			as_user(self.compliance, decline_request, self.request, "No")


class TestContractReferences(ReviewCase):
	def test_compliance_replaces_the_references(self):
		as_user(self.compliance, set_contract_references, self.request, ["CT-1", "CT-2"])
		self.assertEqual(self.references(), ["CT-1", "CT-2"])
		result = as_user(self.compliance, set_contract_references, self.request, ["CT-3"])
		self.assertEqual(self.references(), ["CT-3"])
		self.assertEqual([r["reference"] for r in result["contract_references"]], ["CT-3"])

	def test_blanks_and_repeats_are_dropped(self):
		as_user(self.compliance, set_contract_references, self.request, [" CT-1 ", "", "  ", "CT-1", "CT-2"])
		self.assertEqual(self.references(), ["CT-1", "CT-2"])

	def test_a_long_reference_or_a_bad_value_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			as_user(self.compliance, set_contract_references, self.request, ["x" * 141])
		with self.assertRaises((frappe.ValidationError, TypeError)):  # a string is not a list
			as_user(self.compliance, set_contract_references, self.request, "CT-1")
		with self.assertRaises(frappe.ValidationError):
			as_user(self.compliance, set_contract_references, self.request, [1, 2])
		self.assertEqual(self.references(), [])

	def test_nobody_else_can_set_them(self):
		for user in self.others():
			with self.assertRaises(frappe.PermissionError, msg=user):
				as_user(user, set_contract_references, self.request, ["CT-1"])
		self.assertEqual(self.references(), [])

	def test_not_while_the_job_is_queued_or_running(self):
		for job in ("Queued", "Running"):
			force_request(self.request, erasure_job_status=job)
			with self.assertRaisesRegex(frappe.ValidationError, "Erasure in progress"):
				as_user(self.compliance, set_contract_references, self.request, ["CT-1"])
		self.assertEqual(self.references(), [])

	def test_not_once_the_request_is_finished(self):
		for status in FINISHED:
			force_request(self.request, status=status)
			with self.assertRaises(frappe.ValidationError, msg=status):
				as_user(self.compliance, set_contract_references, self.request, ["CT-1"])
		self.assertEqual(self.references(), [])

	def test_references_can_be_set_while_on_hold(self):
		force_request(self.request, status="On Hold")
		as_user(self.compliance, set_contract_references, self.request, ["CT-9"])
		self.assertEqual(self.references(), ["CT-9"])

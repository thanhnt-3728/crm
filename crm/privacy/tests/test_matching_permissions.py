# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Who may call the matching and submit APIs (RT-1)."""

import frappe

from crm.api.erasure_requests import (
	get_identifier_impact,
	recheck_hold,
	set_identifier_excluded,
	set_match_confirmed,
	submit_request,
	suggest_matches,
)
from crm.privacy.tests.make_test_user import RequestTestCase, as_user, make_lead, make_request

LEAD = "CRM Lead"


class TestWhoMayCall(RequestTestCase):
	"""Another Sales User, the logger after submit, a Sales Manager who is not the logger, and nobody while the
	erasure job is Queued or Running."""

	def setUp(self):
		super().setUp()
		self.lead = make_lead(owner=self.logger, first_name="Row", email="row@example.com")
		self.name = make_request(self.logger, source_doctype=LEAD, source_name=self.lead)
		doc = frappe.get_doc("CRM Erasure Request", self.name)
		self.match_row, self.identifier_row = doc.matches[0].name, doc.identifiers[0].name

	def calls(self):
		n = self.name
		return {
			"suggest_matches": lambda: suggest_matches(n),
			"set_match_confirmed": lambda: set_match_confirmed(n, self.match_row, True),
			"set_identifier_excluded": lambda: set_identifier_excluded(n, self.identifier_row, True),
			"get_identifier_impact": lambda: get_identifier_impact(n),
			"submit_request": lambda: submit_request(n),
		}

	def test_another_sales_user_and_a_non_owning_manager_are_refused(self):
		for user in (self.other, self.manager):
			for label, call in self.calls().items():
				with self.subTest(user=user, call=label), self.assertRaises(frappe.PermissionError):
					as_user(user, call)

	def test_the_logger_is_refused_once_the_request_is_submitted(self):
		self.name = self.submitted_request()
		for label, call in self.calls().items():
			with self.subTest(call=label), self.assertRaises(frappe.PermissionError):
				as_user(self.logger, call)

	def test_nobody_may_call_while_the_erasure_job_is_queued_or_running(self):
		for job in ("Queued", "Running"):
			frappe.db.set_value("CRM Erasure Request", self.name, "erasure_job_status", job)
			for user in (self.logger, self.compliance, "Administrator"):
				for label, call in self.calls().items():
					with (
						self.subTest(job=job, user=user, call=label),
						self.assertRaises(frappe.ValidationError),
					):
						as_user(user, call)

	def test_compliance_can_call_them_on_a_submitted_request(self):
		frappe.db.set_value("CRM Erasure Request", self.name, "status", "Awaiting sign-off")
		as_user(self.compliance, suggest_matches, self.name)
		as_user(self.compliance, get_identifier_impact, self.name)
		as_user(self.compliance, set_identifier_excluded, self.name, self.identifier_row, True)

	def test_nobody_may_call_after_the_erasure(self):
		frappe.db.set_value("CRM Erasure Request", self.name, "status", "Erased")
		for label, call in self.calls().items():
			with (
				self.subTest(call=label),
				self.assertRaises((frappe.ValidationError, frappe.PermissionError)),
			):
				as_user(self.compliance, call)

	def test_recheck_hold_is_for_compliance_on_a_submitted_request(self):
		frappe.db.set_value("CRM Erasure Request", self.name, "status", "Awaiting sign-off")
		for user in (self.logger, self.other, self.manager, "Administrator"):
			with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
				as_user(user, recheck_hold, self.name)
		self.assertEqual(as_user(self.compliance, recheck_hold, self.name)["status"], "Awaiting sign-off")

	def test_recheck_hold_refuses_a_logged_or_frozen_request(self):
		with self.assertRaises(frappe.ValidationError):
			as_user(self.compliance, recheck_hold, self.name)
		frappe.db.set_value(
			"CRM Erasure Request", self.name, {"status": "On Hold", "erasure_job_status": "Running"}
		)
		with self.assertRaises(frappe.ValidationError):
			as_user(self.compliance, recheck_hold, self.name)

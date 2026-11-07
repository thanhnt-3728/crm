# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""get_request and list_requests: what each tier sees, days_left and the `can` action flags."""

import frappe
from frappe.utils import add_days, today

from crm.api.erasure_requests import get_request, list_requests
from crm.privacy.tests.make_test_user import RequestTestCase, force_request, make_request

TRIMMED_KEYS = {"name", "status", "acknowledge_by", "respond_by", "days_left"}
CAN_KEYS = {
	"edit",
	"submit",
	"approve",
	"decline",
	"close",
	"manage_checklist",
	"mark_acknowledged",
	"recheck_hold",
	"set_contract_references",
}
INTERNAL_KEYS = {"approved_plan_hash", "pending_file_deletions"}


def flags_of(user, name):
	frappe.set_user(user)
	return {key for key, value in get_request(name)["can"].items() if value}


class TestGetRequest(RequestTestCase):
	def test_returns_the_full_doc_days_left_and_flags(self):
		name = make_request(self.logger, date_received=add_days(today(), -10))
		frappe.set_user(self.logger)
		result = get_request(name)
		self.assertEqual(result["name"], name)
		self.assertEqual(result["requester_names"], "Marisol Vega")
		self.assertEqual(result["identifiers"][0]["normalized"], "marisol.vega@example.com")
		self.assertEqual(result["days_left"], 35)
		self.assertEqual(set(result["can"]), CAN_KEYS)
		self.assertFalse(INTERNAL_KEYS & set(result))

	def test_days_left_goes_negative_when_overdue(self):
		name = make_request(self.logger, date_received=add_days(today(), -50))
		frappe.set_user(self.logger)
		self.assertEqual(get_request(name)["days_left"], -5)

	def test_logger_is_refused_after_submission_and_others_always(self):
		logged = make_request(self.logger)
		submitted = self.submitted_request()
		frappe.set_user(self.logger)
		with self.assertRaises(frappe.PermissionError):
			get_request(submitted)
		frappe.set_user(self.other)
		for name in (logged, submitted):
			with self.assertRaises(frappe.PermissionError):
				get_request(name)

	def test_manager_and_compliance_read_everything(self):
		for name in (make_request(self.logger), self.submitted_request(status="Erased")):
			for user in (self.manager, self.compliance):
				frappe.set_user(user)
				self.assertEqual(get_request(name)["name"], name)

	def test_unknown_request(self):
		frappe.set_user(self.compliance)
		with self.assertRaises(frappe.DoesNotExistError):
			get_request("PDR-9999")


class TestActionFlags(RequestTestCase):
	def test_logger_on_a_logged_request(self):
		name = make_request(self.logger)
		self.assertEqual(flags_of(self.logger, name), {"edit", "submit"})

	def test_sales_manager_on_someone_elses_request_can_only_look(self):
		self.assertEqual(flags_of(self.manager, make_request(self.logger)), set())

	def test_compliance_per_status(self):
		name = make_request(self.logger)
		expected = {
			"Logged": {
				"edit",
				"submit",
				"decline",
				"manage_checklist",
				"mark_acknowledged",
				"set_contract_references",
			},
			"Awaiting sign-off": {
				"edit",
				"approve",
				"decline",
				"manage_checklist",
				"mark_acknowledged",
				"recheck_hold",
				"set_contract_references",
			},
			"On Hold": {
				"edit",
				"decline",
				"manage_checklist",
				"mark_acknowledged",
				"recheck_hold",
				"set_contract_references",
			},
			"Erased": {"close", "manage_checklist", "mark_acknowledged"},
			"Declined": {"close", "manage_checklist", "mark_acknowledged"},
			"Closed": set(),
		}
		for status, flags in expected.items():
			force_request(name, status=status)
			with self.subTest(status=status):
				self.assertEqual(flags_of(self.compliance, name), flags)

	def test_acknowledged_requests_cannot_be_acknowledged_again(self):
		name = self.submitted_request()
		force_request(name, acknowledgment_sent=1)
		self.assertNotIn("mark_acknowledged", flags_of(self.compliance, name))

	def test_a_frozen_request_offers_nothing(self):
		name = self.submitted_request()
		for job_status in ("Queued", "Running"):
			force_request(name, erasure_job_status=job_status)
			self.assertEqual(flags_of(self.compliance, name), set(), job_status)


class TestListRequests(RequestTestCase):
	def test_logger_sees_own_logged_in_full_and_submitted_trimmed(self):
		logged = make_request(self.logger)
		submitted = self.submitted_request()
		make_request(self.other)
		frappe.set_user(self.logger)
		rows = {row["name"]: row for row in list_requests()}
		self.assertEqual(set(rows), {logged, submitted})
		self.assertEqual(rows[logged]["requester_names"], "Marisol Vega")
		self.assertEqual(set(rows[submitted]), TRIMMED_KEYS)
		self.assertEqual(rows[submitted]["status"], "Awaiting sign-off")
		self.assertEqual(rows[submitted]["days_left"], 45)

	def test_another_sales_user_sees_nothing(self):
		make_request(self.logger)
		self.submitted_request()
		frappe.set_user(self.other)
		self.assertEqual(list_requests(), [])

	def test_manager_and_compliance_see_every_request_in_full(self):
		names = {make_request(self.logger), self.submitted_request(), self.submitted_request(self.other)}
		for user in (self.manager, self.compliance):
			frappe.set_user(user)
			rows = list_requests()
			self.assertEqual({r["name"] for r in rows}, names)
			self.assertTrue(all("requester_names" in r and "days_left" in r for r in rows))
			self.assertFalse(INTERNAL_KEYS & set(rows[0]))

	def test_open_requests_come_first_by_respond_by_then_closed_ones(self):
		late = make_request(self.logger, date_received=add_days(today(), -30))
		early = make_request(self.logger, date_received=add_days(today(), -2))
		closed = make_request(self.logger, date_received=add_days(today(), -40))
		force_request(closed, status="Closed")
		erased = make_request(self.logger, date_received=add_days(today(), -20))
		force_request(erased, status="Erased")
		frappe.set_user(self.compliance)
		self.assertEqual([r["name"] for r in list_requests()], [late, erased, early, closed])

	def test_a_system_manager_without_a_crm_role_cannot_list(self):
		from crm.privacy.tests.make_test_user import make_user

		admin_only = make_user("pdr.sysman@example.com", roles=["System Manager"])
		frappe.set_user(admin_only)
		with self.assertRaises(frappe.PermissionError):
			list_requests()

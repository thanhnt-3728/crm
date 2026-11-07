# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""update_request: editable fields, who may edit and when, typed identifiers (RT-1, RT-4)."""

import frappe
from frappe.utils import add_days, today

from crm.api.erasure_requests import update_request
from crm.privacy.tests.make_test_user import RequestTestCase, force_request, make_request

DT = "CRM Erasure Request"


def stored(name, field):
	return frappe.db.get_value(DT, name, field)


class TestUpdateRequest(RequestTestCase):
	def test_logger_edits_own_logged_request_and_gets_the_fresh_doc(self):
		name = make_request(self.logger, date_received="2026-10-26")
		frappe.set_user(self.logger)
		result = update_request(
			name,
			{
				"requester_names": "Mari Vega",
				"original_message": "Updated",
				"channel": "Phone",
				"date_received": "2026-10-19",
			},
		)
		self.assertEqual((result["requester_names"], result["channel"]), ("Mari Vega", "Phone"))
		self.assertEqual(str(result["respond_by"]), "2026-12-03")
		self.assertIn("can", result)
		self.assertEqual(stored(name, "original_message"), "Updated")

	def test_only_the_editable_fields_are_accepted(self):
		name = make_request(self.logger)
		frappe.set_user(self.logger)
		for field, value in (
			("status", "Awaiting sign-off"),
			("logged_by", self.manager),
			("approver", self.logger),
			("erasure_job_status", "Queued"),
			("respond_by", "2030-01-01"),
			("matches", []),
			("no_such_field", 1),
		):
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				update_request(name, {field: value})
		self.assertEqual(stored(name, "status"), "Logged")

	def test_logger_cannot_edit_after_submission(self):
		name = self.submitted_request()
		frappe.set_user(self.logger)
		with self.assertRaises(frappe.PermissionError):
			update_request(name, {"requester_names": "x"})

	def test_other_users_and_a_manager_on_someone_elses_request_are_refused(self):
		for name in (make_request(self.logger), self.submitted_request()):
			for user in (self.other, self.manager):
				frappe.set_user(user)
				with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
					update_request(name, {"requester_names": "x"})

	def test_compliance_edits_a_submitted_request(self):
		name = self.submitted_request()
		frappe.set_user(self.compliance)
		update_request(name, {"requester_names": "Corrected"})
		self.assertEqual(stored(name, "requester_names"), "Corrected")

	def test_a_frozen_request_refuses_the_edit(self):
		name = self.submitted_request()
		force_request(name, erasure_job_status="Queued")
		frappe.set_user(self.compliance)
		with self.assertRaises(frappe.ValidationError) as ctx:
			update_request(name, {"requester_names": "x"})
		self.assertIn("Erasure in progress", str(ctx.exception))
		self.assertEqual(stored(name, "requester_names"), "Marisol Vega")

	def test_a_future_date_received_is_refused(self):
		name = make_request(self.logger)
		frappe.set_user(self.logger)
		with self.assertRaises(frappe.ValidationError):
			update_request(name, {"date_received": add_days(today(), 1)})


class TestTypedIdentifiers(RequestTestCase):
	def test_emails_and_phones_are_added_normalized_without_duplicates(self):
		name = make_request(self.logger, emails=["marisol.vega@example.com"])
		frappe.set_user(self.logger)
		result = update_request(
			name,
			{"emails": ["Marisol.Vega@example.com", "m@home.org"], "phones": ["(530) 555-0123"]},
		)
		self.assertEqual(
			[(r["kind"], r["normalized"], r["source"]) for r in result["identifiers"]],
			[
				("Email", "marisol.vega@example.com", "Typed"),
				("Email", "m@home.org", "Typed"),
				("Phone", "+15305550123", "Typed"),
			],
		)

	def test_malformed_identifiers_are_refused_and_nothing_is_saved(self):
		name = make_request(self.logger)
		frappe.set_user(self.logger)
		for values in ({"emails": ["a@b"]}, {"emails": ["%"]}, {"phones": ["555"]}):
			with self.subTest(**values), self.assertRaises(frappe.ValidationError):
				update_request(name, {"requester_names": "Changed", **values})
		self.assertEqual(stored(name, "requester_names"), "Marisol Vega")
		self.assertEqual(frappe.db.count("CRM Erasure Identifier", {"parent": name}), 1)

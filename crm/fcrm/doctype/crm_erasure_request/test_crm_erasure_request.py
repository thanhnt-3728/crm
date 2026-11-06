# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import date

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from crm.fcrm.doctype.crm_erasure_request.erasure_guards import assert_can_decide
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	MANAGER,
	PO,
	PO_REP,
	REP,
	REP2,
	approve,
	as_user,
	ensure_users,
	make_contact,
	make_request,
)


class TestCRMErasureRequest(IntegrationTestCase):
	def setUp(self):
		ensure_users()
		self.contact = make_contact()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def log(self, user=REP, **fields):
		with as_user(user):
			return make_request("Contact", self.contact.name, **fields)

	def submitted(self, user=REP):
		request = self.log(user)
		with as_user(user):
			request.submit_for_approval()
		return request

	def test_insert_sets_requester_deadlines_and_draft(self):
		request = self.log(received_on="2026-10-26", requested_by=PO)
		self.assertTrue(request.name.startswith(f"CRM-ERQ-{date.today().year}-"))
		self.assertEqual(request.status, "Draft")
		self.assertEqual(request.requested_by, REP)
		self.assertEqual(getdate(request.ack_due), date(2026, 11, 9))
		self.assertEqual(getdate(request.response_due), date(2026, 12, 10))

	def test_deadlines_follow_settings_holiday_list_on_every_save(self):
		request = self.log(received_on="2026-10-26")
		holiday_list = frappe.get_doc(
			{
				"doctype": "CRM Holiday List",
				"holiday_list_name": "Erasure Test Holidays",
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"holidays": [{"date": "2026-11-03", "description": "Election Day"}],
			}
		).insert()
		frappe.db.set_single_value("FCRM Settings", "erasure_holiday_list", holiday_list.name)
		with as_user(REP):
			request.reload()
			request.subject_name = "Dana T."
			request.save()
		# a later holiday-list edit never moves a running request's deadlines (L2)
		self.assertEqual(getdate(request.ack_due), date(2026, 11, 9))
		with as_user(REP):
			request.received_on = "2026-10-27"
			request.save()
		self.assertEqual(getdate(request.ack_due), date(2026, 11, 11))
		self.assertEqual(getdate(request.response_due), date(2026, 12, 11))

	def test_received_on_cannot_be_in_the_future(self):
		with self.assertRaises(frappe.ValidationError):
			self.log(received_on=add_days(today(), 1))

	def test_insert_cannot_forge_status_or_decision(self):
		for fields in ({"status": "Approved"}, {"approver": PO}, {"executed_on": "2026-10-27 10:00:00"}):
			with self.subTest(fields=fields), self.assertRaises(frappe.ValidationError):
				self.log(**fields)

	def test_status_not_settable_via_save(self):
		request = self.log()
		for user in (REP, "Administrator"):
			with self.subTest(user=user), as_user(user), self.assertRaises(frappe.ValidationError):
				request.reload()
				request.status = "Approved"
				request.save()
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", request.name, "status"), "Draft")

	def test_system_fields_not_settable_via_save_in_draft(self):
		request = self.log()
		with as_user(REP), self.assertRaises(frappe.ValidationError):
			request.approver = PO
			request.save()

	def test_requester_edits_only_in_draft(self):
		request = self.log()
		with as_user(REP):
			request.append("identifiers", {"kind": "Phone", "value": "+1 555 0100"})
			self.assertRaises(frappe.ValidationError, request.save)  # identifiers: set_identifiers only
			request.reload()
			request.subject_name = "Dana Edited"
			request.save()
			request.submit_for_approval()
		self.assertEqual(request.status, "Pending Approval")
		edits = (
			("subject_name", "Dana Again"),
			("received_on", add_days(today(), -1)),
			("source_docname", "other"),
		)
		for field, value in edits:
			with self.subTest(field=field), as_user(REP), self.assertRaises(frappe.ValidationError):
				request.reload()
				request.set(field, value)
				request.save()
		with as_user(REP), self.assertRaises(frappe.ValidationError):
			request.reload()
			request.identifiers[0].value = "other@example.com"
			request.save()

	def test_acknowledged_on_editable_after_draft_by_requester_or_po(self):
		request = self.submitted()
		for user in (REP, PO):
			with self.subTest(user=user), as_user(user):
				request.reload()
				request.acknowledged_on = today()
				request.save()
		self.assertEqual(getdate(request.acknowledged_on), getdate(today()))
		with as_user(REP), self.assertRaises(frappe.ValidationError):
			request.reload()
			request.acknowledged_on = add_days(today(), 1)
			request.save()
		with as_user(MANAGER), self.assertRaises(frappe.PermissionError):
			request.reload()
			request.acknowledged_on = add_days(today(), -1)
			request.save()

	def test_terminal_request_is_read_only(self):
		request = self.log()
		with as_user(PO):
			request.reload()
			request.transition_to("Rejected", rejection_reason="Not verifiable")
		with as_user(PO), self.assertRaises(frappe.ValidationError):
			request.reload()
			request.acknowledged_on = today()
			request.save()

	def test_approval_guards(self):
		request = self.submitted(PO_REP)
		for user, error in ((PO_REP, frappe.PermissionError), (MANAGER, frappe.PermissionError)):
			with self.subTest(user=user), as_user(user), self.assertRaises(error):
				assert_can_decide(request)
			with self.subTest(user=user), as_user(user), self.assertRaises(error):
				request.reload()
				request.transition_to("Approved", approver=user)
		self.assertEqual(
			frappe.db.get_value("CRM Erasure Request", request.name, "status"), "Pending Approval"
		)

		approve(request, PO)
		request.reload()
		self.assertEqual(request.status, "Approved")
		self.assertEqual(request.approver, PO)

	def test_reject_needs_decider_and_illegal_transitions_fail(self):
		request = self.log()
		with as_user(REP), self.assertRaises(frappe.PermissionError):
			request.transition_to("Rejected")
		with as_user(PO), self.assertRaises(frappe.ValidationError):
			request.reload()
			request.transition_to("Approved")  # Draft -> Approved skips submission
		with as_user(PO), self.assertRaises(ValueError):
			request.transition_to("Rejected", subject_name="forged")
		with as_user(REP2), self.assertRaises(frappe.PermissionError):
			request.reload()
			request.submit_for_approval()  # only the requester submits

	def test_close_and_execute_actors(self):
		request = approve(self.submitted(), PO)
		request.transition_to("Executed", executed_on=frappe.utils.now_datetime())
		with as_user(REP), self.assertRaises(frappe.PermissionError):
			request.reload()
			request.transition_to("Closed")
		with as_user(PO):
			request.reload()
			request.transition_to("Closed")
		self.assertEqual(request.status, "Closed")

	def test_save_system_fields_keeps_status(self):
		request = approve(self.submitted(), PO)
		request.save_system_fields(last_error="ProgrammingError in Communication")
		self.assertEqual(request.status, "Approved")
		self.assertEqual(request.last_error, "ProgrammingError in Communication")
		with self.assertRaises(ValueError):
			request.save_system_fields(status="Executed")

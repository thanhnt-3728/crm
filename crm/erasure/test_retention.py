# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import UnitTestCase

from crm.api import erasure as api
from crm.erasure import jobs
from crm.erasure.erasure_test_fixture_execution import (
	REQUEST,
	approved_marisol_request,
	commits_recorded,
	her_identifier_strings,
)
from crm.erasure.registry_model import name_marker
from crm.erasure.retention import mask_email, mask_phone, retention_rows
from crm.erasure.test_executor import ExecutorCase
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import PO, REP, as_user

class TestMasking(UnitTestCase):
	def test_masks(self):
		self.assertEqual(mask_email("marisol.reyes@example.net"), "m***@example.net")
		self.assertEqual(mask_email("M@example.net"), "m***@example.net")
		self.assertEqual(mask_phone("+14155550123"), "***0123")
		self.assertEqual(mask_phone("+14155550123;ext=12"), "***0123")
		self.assertEqual(mask_phone("12"), "***")

	def test_retention_rows_hold_no_identifier(self):
		request = frappe._dict(
			identifiers=[
				frappe._dict(kind="Email", value="Marisol.Reyes@example.net", normalized="marisol.reyes@example.net"),
				frappe._dict(kind="Phone", value="(415) 555-0123", normalized="+14155550123"),
			]
		)
		rows = retention_rows(request)
		self.assertEqual(
			rows,
			[
				{"kind": "Email", "value": "m***@example.net", "normalized": "m***@example.net"},
				{"kind": "Phone", "value": "***0123", "normalized": "***0123"},
			],
		)


class TestClose(ExecutorCase):
	def executed(self):
		request = approved_marisol_request(self.fx)
		with commits_recorded():
			jobs.execute_request(request.name)
		self.assertEqual(frappe.db.get_value(REQUEST, request.name, "status"), "Executed")
		return request

	def test_close_needs_a_privacy_officer(self):
		request = self.executed()
		with as_user(REP), self.assertRaises(frappe.PermissionError):
			api.close(request.name)
		self.assertEqual(frappe.db.get_value(REQUEST, request.name, "status"), "Executed")

	def test_close_applies_retention(self):
		request = self.executed()
		with as_user(PO), commits_recorded() as commit:
			self.assertEqual(api.close(request.name)["status"], "Closed")
		commit.assert_not_called()  # close and retention are one transaction
		closed = frappe.get_doc(REQUEST, request.name)
		self.assertEqual(closed.subject_name, name_marker(request.name))
		self.assertEqual([(r.kind, r.value) for r in closed.identifiers], [(r["kind"], r["value"]) for r in retention_rows(request)])
		stored = frappe.as_json(closed.as_dict()).lower()
		for text in her_identifier_strings()[:4]:  # emails and phone digits; Contact names stay (see report)
			self.assertNotIn(text.lower(), stored)
		self.assertTrue(closed.ack_due and closed.response_due and closed.executed_on and closed.approved_on)

	def test_retention_seam_is_guarded(self):
		request = self.executed()
		rows = retention_rows(request)
		with as_user(PO), self.assertRaises(frappe.ValidationError):
			frappe.get_doc(REQUEST, request.name).apply_retention_rows(rows, "x")  # not Closed yet
		with as_user(PO):
			frappe.get_doc(REQUEST, request.name).transition_to("Closed")
		with as_user(REP), self.assertRaises(frappe.PermissionError):
			frappe.get_doc(REQUEST, request.name).apply_retention_rows(rows, "x")
		with as_user(PO), self.assertRaises(ValueError):
			frappe.get_doc(REQUEST, request.name).apply_retention_rows([{**rows[0], "extra": 1}], "x")
		self.assertEqual(frappe.db.get_value(REQUEST, request.name, "subject_name"), "Marisol Reyes")

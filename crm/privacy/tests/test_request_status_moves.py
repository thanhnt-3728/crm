# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Status moves and the frozen-while-erasing rule of CRM Erasure Request (RT-1, design 5.2)."""

import frappe

from crm.privacy.request_status import server_write
from crm.privacy.tests.make_test_user import force_request
from crm.privacy.tests.test_request_guard import DT, GuardTestCase, payload_of


class TestStatusMoves(GuardTestCase):
	def move(self, **values):
		with server_write():
			doc = frappe.get_doc(DT, self.name)
			doc.update(values)
			doc.save(ignore_permissions=True)

	def test_a_permitted_move_is_saved(self):
		self.move(status="Awaiting sign-off")
		self.move(status="On Hold")
		self.move(status="Awaiting sign-off")
		self.move(status="Erased")
		self.move(status="Closed")
		self.assertEqual(frappe.db.get_value(DT, self.name, "status"), "Closed")

	def test_a_forbidden_move_throws_even_for_the_server(self):
		for target in ("Erased", "Closed"):
			with self.assertRaises(frappe.ValidationError):
				self.move(status=target)
		self.assertEqual(frappe.db.get_value(DT, self.name, "status"), "Logged")

	def test_declining_needs_a_reason(self):
		with self.assertRaises(frappe.ValidationError):
			self.move(status="Declined")
		self.move(status="Declined", denial_reason="Identity not verifiable")
		self.assertEqual(frappe.db.get_value(DT, self.name, "status"), "Declined")


class TestFrozenWhileErasing(GuardTestCase):
	def test_a_queued_or_running_request_refuses_every_write(self):
		for job_status in ("Queued", "Running"):
			force_request(self.name, erasure_job_status=job_status)
			frappe.set_user(self.compliance)
			payload = payload_of(self.name)
			payload["requester_names"] = "Changed"
			with self.subTest(job=job_status):
				with self.assertRaises(frappe.ValidationError) as ctx:
					frappe.client.save(payload)
				self.assertIn("Erasure in progress", str(ctx.exception))
				with self.assertRaises(frappe.ValidationError), server_write():
					doc = frappe.get_doc(DT, self.name)
					doc.status = "Declined"
					doc.denial_reason = "x"
					doc.save(ignore_permissions=True)

	def test_the_executor_can_write_while_frozen(self):
		force_request(self.name, status="Awaiting sign-off", erasure_job_status="Running")
		with server_write(frozen_ok=True):
			doc = frappe.get_doc(DT, self.name)
			doc.status = "Erased"
			doc.erasure_job_status = ""
			doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value(DT, self.name, "status"), "Erased")

	def test_a_failed_job_does_not_freeze_the_request(self):
		force_request(self.name, erasure_job_status="Failed")
		frappe.set_user(self.compliance)
		payload = payload_of(self.name)
		payload["requester_names"] = "Changed"
		frappe.client.save(payload)

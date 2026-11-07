# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Phase 02 review fixes: finished requests are immutable (H1), Compliance-only fields (M1),
no sharing or assigning (M2), list-typed identifiers (L1)."""

import frappe
import frappe.share
from frappe.desk.form.assign_to import add as assign_add

from crm.api.erasure_requests import update_request
from crm.privacy.request_status import server_write
from crm.privacy.tests.make_test_user import force_request
from crm.privacy.tests.test_request_guard import DT, GuardTestCase, payload_of

FINISHED = ("Erased", "Declined", "Closed")
EDITABLE = ("Logged", "Awaiting sign-off", "On Hold")


class TestFinishedRequestsAreImmutable(GuardTestCase):
	def test_update_request_is_refused_on_a_finished_request(self):
		frappe.set_user(self.compliance)
		for status in FINISHED:
			force_request(self.name, status=status)
			for values in ({"requester_names": "changed"}, {"emails": ["new.pii@example.com"]}):
				with (
					self.subTest(status=status, values=list(values)),
					self.assertRaises(frappe.ValidationError),
				):
					update_request(self.name, values)
		self.assertEqual(frappe.db.count("CRM Erasure Identifier", {"parent": self.name}), 1)

	def test_update_request_still_works_before_the_erasure(self):
		frappe.set_user(self.compliance)
		for status in EDITABLE:
			force_request(self.name, status=status)
			update_request(self.name, {"requester_names": f"Edited in {status}"})

	def test_set_value_and_save_are_refused_on_a_finished_request(self):
		frappe.set_user(self.compliance)
		for status in FINISHED:
			force_request(self.name, status=status)
			for field, value in (
				("requester_names", "x"),
				("date_received", "2026-01-01"),
				("channel", "Mail"),
			):
				with self.subTest(status=status, set_value=field), self.assertRaises(frappe.ValidationError):
					frappe.client.set_value(DT, self.name, field, value)
			payload = payload_of(self.name)
			payload["requester_names"] = "x"
			with (
				self.subTest(status=status, save="requester_names"),
				self.assertRaises(frappe.ValidationError),
			):
				frappe.client.save(payload)
			payload = payload_of(self.name)
			payload["matches"][0]["label"] = "changed"
			with self.subTest(status=status, save="match row"), self.assertRaises(frappe.ValidationError):
				frappe.client.save(payload)
			self.assertEqual(frappe.db.get_value(DT, self.name, "requester_names"), "Marisol Vega")

	def test_the_dates_of_a_closed_request_cannot_move(self):
		force_request(self.name, status="Closed")
		frappe.set_user(self.compliance)
		before = frappe.db.get_value(DT, self.name, "respond_by")
		with self.assertRaises(frappe.ValidationError):
			frappe.client.set_value(DT, self.name, {"outcome": "Denied", "date_received": "2026-01-01"})
		self.assertEqual(frappe.db.get_value(DT, self.name, "respond_by"), before)

	def test_the_server_can_still_write_a_finished_request(self):
		for status in FINISHED:
			force_request(self.name, status=status)
			with server_write():
				doc = frappe.get_doc(DT, self.name)
				doc.checklist[0].done = 1
				doc.requester_names = f"Wiped in {status}"
				doc.save(ignore_permissions=True)
			self.assertEqual(frappe.db.get_value(DT, self.name, "requester_names"), f"Wiped in {status}")

	def test_can_edit_is_false_once_finished(self):
		from crm.api.erasure_requests import get_request

		frappe.set_user(self.compliance)
		for status in FINISHED:
			force_request(self.name, status=status)
			self.assertFalse(get_request(self.name)["can"]["edit"], status)


class TestComplianceOnlyFields(GuardTestCase):
	def test_logger_and_sales_manager_cannot_set_them(self):
		own_manager = self.make_request_for(self.manager)
		for user, name in ((self.logger, self.name), (self.manager, own_manager)):
			frappe.set_user(user)
			for field, value in (
				("outcome", "Denied"),
				("date_answered", frappe.utils.today()),
				("denial_reason", "x"),
			):
				with self.subTest(user=user, field=field), self.assertRaises(frappe.ValidationError):
					frappe.client.set_value(DT, name, field, value)

	def make_request_for(self, user):
		from crm.privacy.tests.make_test_user import make_request

		return make_request(user)


class TestNoSharing(GuardTestCase):
	def test_an_administrator_share_is_refused_with_a_clear_message(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.share.add(DT, self.name, user=self.other)
		self.assertIn("can't be shared or assigned", str(ctx.exception))
		self.assertFalse(frappe.db.exists("DocShare", {"share_doctype": DT, "share_name": self.name}))

	def test_assigning_a_request_is_refused(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			assign_add({"doctype": DT, "name": self.name, "assign_to": [self.other]})
		self.assertFalse(frappe.db.exists("DocShare", {"share_doctype": DT, "share_name": self.name}))

	def test_other_doctypes_can_still_be_shared(self):
		from crm.privacy.tests.make_test_user import make_lead

		lead = make_lead()
		frappe.set_user("Administrator")
		frappe.share.add("CRM Lead", lead, user=self.other)
		self.assertTrue(frappe.db.exists("DocShare", {"share_doctype": "CRM Lead", "share_name": lead}))

	def test_a_sales_user_still_sees_nothing(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			frappe.share.add(DT, self.name, user=self.other)
		force_request(self.name, status="Awaiting sign-off")
		frappe.set_user(self.other)
		self.assertEqual(frappe.get_list(DT, fields=["*"]), [])
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get(DT, self.name)


class TestIdentifierListsMustBeLists(GuardTestCase):
	def test_a_string_is_refused_with_a_clear_message(self):
		frappe.set_user(self.logger)
		for key in ("emails", "phones"):
			with self.subTest(key=key), self.assertRaises(frappe.ValidationError) as ctx:
				update_request(self.name, {key: "a.b@example.com"})
			self.assertIn("must be a list", str(ctx.exception))

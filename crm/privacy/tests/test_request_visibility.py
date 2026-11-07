# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Who can see and write a CRM Erasure Request (design 5.1), through every generic endpoint."""

import json

import frappe
from frappe.desk.form.load import getdoc

from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	force_request,
	make_contact,
	make_deal,
	make_lead,
	make_request,
	make_user,
)

DT = "CRM Erasure Request"
CHILD_DOCTYPES = (
	"CRM Erasure Identifier",
	"CRM Erasure Match",
	"CRM Erasure Checklist Item",
	"CRM Erasure Contract Reference",
)


def can(user, ptype, name):
	return frappe.has_permission(DT, ptype, name, user=user)


class TestLoggerVisibility(RequestTestCase):
	def test_logger_reads_and_writes_own_logged_request(self):
		name = make_request(self.logger)
		self.assertTrue(can(self.logger, "read", name))
		self.assertTrue(can(self.logger, "write", name))

	def test_after_submission_the_logger_is_denied_outright(self):
		name = self.submitted_request()
		self.assertFalse(can(self.logger, "read", name))
		self.assertFalse(can(self.logger, "write", name))
		frappe.set_user(self.logger)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(DT, name).check_permission("read")

	def test_every_later_status_stays_hidden_from_the_logger(self):
		for status in ("On Hold", "Erased", "Declined", "Closed"):
			name = self.submitted_request(status=status)
			self.assertFalse(can(self.logger, "read", name), status)

	def test_a_forged_in_memory_status_does_not_reopen_the_request(self):
		name = self.submitted_request()
		doc = frappe.get_doc(DT, name)
		doc.status = "Logged"  # what a crafted frappe.client.save payload would carry
		self.assertFalse(frappe.has_permission(doc=doc, ptype="write", user=self.logger))

	def test_another_sales_user_never_sees_it(self):
		logged = make_request(self.logger)
		submitted = self.submitted_request()
		for name in (logged, submitted):
			self.assertFalse(can(self.other, "read", name))
			self.assertFalse(can(self.other, "write", name))

	def test_nobody_but_the_administrator_can_delete(self):
		name = make_request(self.logger)
		for user in (self.logger, self.manager, self.compliance):
			self.assertFalse(can(user, "delete", name), user)

	def test_everyone_with_a_crm_role_can_create(self):
		for user in (self.logger, self.manager, self.compliance):
			self.assertTrue(frappe.has_permission(DT, "create", user=user), user)


class TestManagerAndCompliance(RequestTestCase):
	def test_sales_manager_reads_everything(self):
		for name in (make_request(self.logger), self.submitted_request(status="Erased")):
			self.assertTrue(can(self.manager, "read", name))

	def test_sales_manager_cannot_write_someone_elses_request(self):
		for name in (make_request(self.logger), self.submitted_request()):
			self.assertFalse(can(self.manager, "write", name))

	def test_sales_manager_writes_only_their_own_logged_request(self):
		own = make_request(self.manager)
		self.assertTrue(can(self.manager, "write", own))
		force_request(own, status="Awaiting sign-off")
		self.assertFalse(can(self.manager, "write", own))

	def test_compliance_reads_and_writes_everything(self):
		for name in (make_request(self.logger), self.submitted_request(status="Closed")):
			self.assertTrue(can(self.compliance, "read", name))
			self.assertTrue(can(self.compliance, "write", name))

	def test_system_manager_alone_is_not_enough(self):
		admin_only = make_user("pdr.sysman@example.com", roles=["System Manager"])
		self.assertFalse(can(admin_only, "read", make_request(self.logger)))

	def test_administrator_is_unrestricted(self):
		self.assertTrue(can("Administrator", "read", self.submitted_request()))


class TestGenericEndpointsDoNotLeak(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.name = self.submitted_request()
		frappe.set_user(self.logger)

	def test_frappe_client_get(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get(DT, self.name)

	def test_getdoc(self):
		with self.assertRaises(frappe.PermissionError):
			getdoc(DT, self.name)

	def test_get_list_with_every_field(self):
		self.assertEqual(frappe.get_list(DT, fields=["*"]), [])
		self.assertEqual(frappe.client.get_list(DT, fields=["*"]), [])

	def test_get_value_and_count(self):
		self.assertFalse(frappe.client.get_value(DT, "requester_names", {"name": self.name}))
		self.assertEqual(frappe.client.get_count(DT), 0)

	def test_child_tables_cannot_be_listed_around_the_parent(self):
		frappe.set_user("Administrator")
		with_children = make_request(self.logger)
		frappe.set_user(self.logger)
		for child in CHILD_DOCTYPES:
			rows = frappe.get_list(child, parent_doctype=DT, fields=["*"], limit_page_length=0)
			self.assertEqual({r.parent for r in rows} - {with_children}, set(), child)

	def test_the_logger_still_sees_own_logged_request_and_children(self):
		frappe.set_user("Administrator")
		logged = make_request(self.logger, emails=["x.person@example.com"])
		frappe.set_user(self.logger)
		self.assertEqual([r.name for r in frappe.get_list(DT)], [logged])
		identifiers = frappe.get_list(
			"CRM Erasure Identifier", parent_doctype=DT, fields=["parent", "value"], limit_page_length=0
		)
		self.assertEqual([(r.parent, r.value) for r in identifiers], [(logged, "x.person@example.com")])

	def test_manager_lists_every_request(self):
		frappe.set_user(self.manager)
		self.assertIn(self.name, [r.name for r in frappe.get_list(DT)])
		frappe.client.get(DT, self.name)

	def test_save_payload_for_a_hidden_request_is_refused(self):
		frappe.set_user(self.logger)
		payload = json.loads(
			frappe.as_json(frappe.get_doc(DT, self.name)),
		)
		payload["status"] = "Logged"
		with self.assertRaises(frappe.PermissionError):
			frappe.client.save(payload)


class TestDeletingMatchedRecords(RequestTestCase):
	def test_a_record_named_in_a_request_can_still_be_deleted_without_naming_the_request(self):
		lead = make_lead()
		contact = make_contact("Zed", emails=["z@acme.com"])
		deal = make_deal([contact])
		make_request(self.manager, source_doctype="CRM Lead", source_name=lead, emails=None)
		make_request(self.manager, source_doctype="CRM Deal", source_name=deal, emails=None)
		for doctype, name in (("CRM Lead", lead), ("CRM Deal", deal), ("Contact", contact)):
			frappe.delete_doc(doctype, name)
			self.assertFalse(frappe.db.exists(doctype, name))

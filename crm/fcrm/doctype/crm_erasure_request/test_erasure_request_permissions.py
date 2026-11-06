# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	MANAGER,
	PO,
	REP,
	REP2,
	as_user,
	ensure_users,
	make_contact,
	make_request,
)
from crm.patches.v1_0 import add_privacy_officer_role as role_patch


class TestErasureRequestPermissions(IntegrationTestCase):
	def setUp(self):
		ensure_users()
		self.contact = make_contact()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def log(self, user=REP):
		with as_user(user):
			return make_request("Contact", self.contact.name)

	def test_sales_user_sees_only_own_requests_and_cannot_delete(self):
		request = self.log()

		def allowed(ptype, user):
			return bool(frappe.has_permission("CRM Erasure Request", ptype, doc=request, user=user))

		self.assertTrue(allowed("read", REP))
		self.assertTrue(allowed("write", REP))
		self.assertFalse(allowed("delete", REP))
		self.assertFalse(allowed("read", REP2))
		self.assertTrue(allowed("read", MANAGER))
		self.assertFalse(allowed("write", MANAGER))
		self.assertFalse(allowed("delete", MANAGER))
		self.assertTrue(allowed("write", PO))
		self.assertFalse(allowed("delete", PO))
		self.assertTrue(allowed("delete", "Administrator"))
		with as_user(REP2):
			names = frappe.get_list("CRM Erasure Request", pluck="name")
		self.assertNotIn(request.name, names)

	def test_privacy_officer_role_patch_is_idempotent(self):
		frappe.db.delete("Role", {"name": "Privacy Officer"})
		role_patch.execute()
		role_patch.execute()
		self.assertEqual(frappe.db.count("Role", {"name": "Privacy Officer"}), 1)
		self.assertEqual(frappe.db.get_value("Role", "Privacy Officer", "desk_access"), 1)

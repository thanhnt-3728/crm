# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A user whose only CRM role is Compliance passes the CRM gate, like `check_app_permission` says (phase 07 fix round)."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.session import (
	CRM_ALLOWED_ROLES,
	get_organizations,
	get_session_role_flags,
	get_user_info,
	get_users,
)
from crm.privacy.install import setup
from crm.privacy.tests.make_test_user import as_user, make_user


class TestComplianceSession(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		self.dana = make_user("pdr.session.dana@example.com", roles=["Compliance"])
		self.sales = make_user("pdr.session.sales@example.com", roles=["Sales User"])
		self.nobody = make_user("pdr.session.nobody@example.com", roles=["Desk User"])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_compliance_is_an_allowed_crm_role(self):
		self.assertIn("Compliance", CRM_ALLOWED_ROLES)

	def test_a_compliance_only_user_passes_the_gate(self):
		flags = as_user(self.dana, get_session_role_flags)
		self.assertFalse(any(flags.values()))  # not a manager, admin or sales user: no more than the gate

	def test_a_compliance_only_user_is_listed_as_compliance_not_as_assignable(self):
		users, crm_users, compliance_users = as_user(self.dana, get_users)
		me = next((u for u in compliance_users if u.name == self.dana), None)
		self.assertIsNotNone(me, "the SPA's isCrmUser() would send this user to Not Permitted")
		self.assertEqual(me.role, "Compliance")
		self.assertIn(self.dana, [u.name for u in users])  # names resolve like any user's
		self.assertNotIn(self.dana, [u.name for u in crm_users])  # the list behind assignment pickers

	def test_no_assignable_list_holds_a_compliance_only_user(self):
		for viewer in (self.sales, "Administrator"):
			with self.subTest(viewer=viewer):
				_, crm_users, compliance_users = as_user(viewer, get_users)
				self.assertNotIn(self.dana, [u.name for u in crm_users])
				self.assertIn(self.dana, [u.name for u in compliance_users])
		_, crm_users, _ = as_user("Administrator", get_users, True)  # the full list
		self.assertNotIn(self.dana, [u.name for u in crm_users])

	def test_a_sales_user_is_never_in_the_compliance_list(self):
		for viewer in (self.sales, self.dana):
			_, crm_users, compliance_users = as_user(viewer, get_users)
			self.assertIn(self.sales, [u.name for u in crm_users])
			self.assertNotIn(self.sales, [u.name for u in compliance_users])

	def test_get_organizations_gives_a_compliance_only_user_nothing(self):
		frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Sierra Foothills Dental"}
		).insert(ignore_permissions=True)
		self.assertTrue(as_user(self.sales, get_organizations))
		self.assertEqual(as_user(self.dana, get_organizations), [])

	def test_the_other_session_endpoints_accept_them_too(self):
		as_user(self.dana, get_user_info, [self.dana])
		as_user(self.dana, get_organizations)

	def test_a_user_with_no_crm_role_is_still_refused(self):
		for call in (get_session_role_flags, get_users, get_organizations):
			with self.subTest(call=call.__name__), self.assertRaises(frappe.PermissionError):
				as_user(self.nobody, call)

	def test_a_user_with_a_sales_role_keeps_that_role_even_with_compliance(self):
		frappe.get_doc("User", self.sales).add_roles("Compliance")
		_, crm_users, _ = as_user(self.sales, get_users)
		me = next(u for u in crm_users if u.name == self.sales)
		self.assertEqual(me.role, "Sales User")

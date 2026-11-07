# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Compliance is an explicit grant: Administrator and System Manager do not get it for free."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.api import check_app_permission
from crm.privacy.install import setup
from crm.privacy.roles import get_compliance_users, has_explicit_role
from crm.privacy.tests.make_test_user import make_user

ROLE = "Compliance"


class TestRoles(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_administrator_without_an_explicit_row_is_not_compliance(self):
		self.assertIn(ROLE, frappe.get_roles("Administrator"))  # the trap: get_roles says yes
		self.assertFalse(has_explicit_role("Administrator", ROLE))

	def test_explicit_assignment_is_recognised(self):
		user = make_user("compliance.one@example.com", roles=[ROLE])
		self.assertTrue(has_explicit_role(user, ROLE))

	def test_user_without_the_role_is_not_compliance(self):
		user = make_user("sales.one@example.com", roles=["Sales User"])
		self.assertFalse(has_explicit_role(user, ROLE))

	def test_system_manager_is_not_compliance(self):
		user = make_user("sysman.one@example.com", roles=["System Manager"])
		self.assertFalse(has_explicit_role(user, ROLE))

	def test_administrator_with_an_explicit_row_is_compliance(self):
		admin = frappe.get_doc("User", "Administrator")
		admin.append("roles", {"role": ROLE})
		admin.save()
		self.assertTrue(has_explicit_role("Administrator", ROLE))

	def test_empty_user_or_role_is_false(self):
		self.assertFalse(has_explicit_role("", ROLE))
		self.assertFalse(has_explicit_role(None, ROLE))
		self.assertFalse(has_explicit_role("Administrator", ""))

	def test_compliance_users_lists_only_enabled_explicit_holders(self):
		on = make_user("compliance.on@example.com", roles=[ROLE])
		make_user("compliance.off@example.com", roles=[ROLE], enabled=0)
		make_user("other.one@example.com", roles=["Sales Manager"])
		users = get_compliance_users()
		self.assertIn(on, users)
		self.assertNotIn("compliance.off@example.com", users)
		self.assertNotIn("other.one@example.com", users)
		self.assertNotIn("Administrator", users)

	def test_compliance_users_are_system_users_only(self):
		web = make_user("compliance.web@example.com", roles=[ROLE])
		frappe.db.set_value("User", web, "user_type", "Website User")
		system = make_user("compliance.sys@example.com", roles=[ROLE])
		self.assertEqual(frappe.db.get_value("User", system, "user_type"), "System User")
		users = get_compliance_users()
		self.assertIn(system, users)
		self.assertNotIn(web, users)

	def test_guest_and_administrator_are_never_listed_even_with_an_explicit_row(self):
		for name in ("Guest", "Administrator"):
			user = frappe.get_doc("User", name)
			user.append("roles", {"role": ROLE})
			user.flags.ignore_validate = True
			user.save(ignore_permissions=True)
		users = get_compliance_users()
		self.assertNotIn("Guest", users)
		self.assertNotIn("Administrator", users)

	def test_compliance_role_has_desk_access_like_sales_user(self):
		self.assertEqual(frappe.db.get_value("Role", ROLE, "desk_access"), 1)
		self.assertEqual(frappe.db.get_value("Role", "Sales User", "desk_access"), 1)

	def test_setup_turns_desk_access_back_on_for_an_existing_compliance_role(self):
		frappe.db.set_value("Role", ROLE, "desk_access", 0)
		setup()
		self.assertEqual(frappe.db.get_value("Role", ROLE, "desk_access"), 1)

	def test_a_user_with_only_compliance_can_open_the_crm(self):
		user = make_user("compliance.only@example.com", roles=[ROLE])
		frappe.set_user(user)
		try:
			self.assertTrue(check_app_permission())
		finally:
			frappe.set_user("Administrator")

	def test_a_user_with_an_unrelated_role_still_cannot_open_the_crm(self):
		user = make_user("blogger.only@example.com", roles=["Newsletter Manager"])
		frappe.set_user(user)
		try:
			self.assertFalse(check_app_permission())
		finally:
			frappe.set_user("Administrator")

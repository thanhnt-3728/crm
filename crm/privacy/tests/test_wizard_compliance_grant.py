# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Frappe's setup wizard gives its first user every Role that exists, Compliance included. The
`setup_wizard_complete` hook takes the role back from anyone whose grant has no audit Comment (M1; safety-critical:
permissions)."""

import frappe
from frappe.desk.page.setup_wizard.setup_wizard import _get_default_roles
from frappe.tests import IntegrationTestCase

from crm.api.erasure_review import set_compliance_member
from crm.privacy.compliance_members import revoke_unaudited_grants
from crm.privacy.install import setup
from crm.privacy.roles import COMPLIANCE_ROLE, has_explicit_role
from crm.privacy.tests.make_test_user import as_user, make_user
from crm.privacy.tests.test_compliance_member import audit_comments

HOOK = "crm.privacy.compliance_members.revoke_unaudited_grants"


class TestSetupWizardGrant(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		self.admin = make_user("pdr.sysman@example.com", roles=["System Manager"])
		self.wizard_user = make_user("pdr.founder@example.com", roles=["System Manager"])
		user = frappe.get_doc("User", self.wizard_user)
		user.append_roles(*_get_default_roles())  # what `create_or_update_user` does for the first user
		user.save(ignore_permissions=True)
		self.granted = make_user("pdr.dana@example.com", roles=["Sales User"])
		as_user(self.admin, set_compliance_member, self.granted, True)
		self.before = len(audit_comments())

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_the_wizard_really_gives_the_first_user_the_role(self):
		self.assertTrue(has_explicit_role(self.wizard_user, COMPLIANCE_ROLE))

	def test_the_hook_takes_the_role_from_a_user_with_no_audited_grant(self):
		revoke_unaudited_grants({})
		self.assertFalse(has_explicit_role(self.wizard_user, COMPLIANCE_ROLE))
		self.assertIn("System Manager", frappe.get_roles(self.wizard_user))

	def test_a_user_granted_through_the_privacy_page_keeps_the_role(self):
		revoke_unaudited_grants({})
		self.assertTrue(has_explicit_role(self.granted, COMPLIANCE_ROLE))

	def test_a_user_whose_grant_was_later_revoked_and_regiven_by_hand_loses_it(self):
		as_user(self.admin, set_compliance_member, self.granted, False)
		frappe.get_doc("User", self.granted).add_roles(COMPLIANCE_ROLE)
		revoke_unaudited_grants({})
		self.assertFalse(has_explicit_role(self.granted, COMPLIANCE_ROLE))

	def test_it_leaves_one_comment_with_the_count_and_no_user(self):
		revoke_unaudited_grants({})
		(comment,) = audit_comments()[self.before :]
		self.assertIn("1", comment)
		self.assertNotIn("pdr.", comment)

	def test_running_it_again_changes_nothing(self):
		revoke_unaudited_grants({})
		revoke_unaudited_grants({})
		self.assertEqual(len(audit_comments()[self.before :]), 1)

	def test_the_hook_is_registered_for_the_setup_wizard(self):
		self.assertIn(HOOK, frappe.get_hooks("setup_wizard_complete"))

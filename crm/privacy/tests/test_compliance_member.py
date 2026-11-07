# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""`set_compliance_member`: only a System Manager grants or revokes Compliance, never for themselves,
the grant is an explicit Has Role row and every change leaves an audit Comment (V1; safety-critical: permissions)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.erasure_review import set_compliance_member
from crm.privacy.install import setup
from crm.privacy.roles import COMPLIANCE_ROLE, get_compliance_users, has_explicit_role
from crm.privacy.tests.make_test_user import as_user, make_user

SETTINGS = "CRM Privacy Settings"


def audit_comments() -> list[str]:
	return frappe.get_all(
		"Comment",
		{"reference_doctype": SETTINGS, "reference_name": SETTINGS, "comment_type": "Info"},
		pluck="content",
		order_by="creation asc",
	)


class TestSetComplianceMember(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		self.admin = make_user("pdr.sysman@example.com", roles=["System Manager"])
		self.target = make_user("pdr.dana@example.com", roles=["Sales User"])
		self.before = len(audit_comments())

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def new_comments(self) -> list[str]:
		return audit_comments()[self.before :]

	def test_a_system_manager_grants_an_explicit_has_role_row(self):
		as_user(self.admin, set_compliance_member, self.target, True)
		self.assertTrue(has_explicit_role(self.target, COMPLIANCE_ROLE))
		self.assertIn(self.target, get_compliance_users())

	def test_a_grant_writes_an_audit_comment_naming_both_users(self):
		as_user(self.admin, set_compliance_member, self.target, True)
		comments = self.new_comments()
		self.assertEqual(len(comments), 1)
		self.assertIn(self.admin, comments[0])
		self.assertIn(self.target, comments[0])
		self.assertIn("granted", comments[0])

	def test_revoke_removes_the_row_and_is_audited(self):
		as_user(self.admin, set_compliance_member, self.target, True)
		as_user(self.admin, set_compliance_member, self.target, False)
		self.assertFalse(has_explicit_role(self.target, COMPLIANCE_ROLE))
		comments = self.new_comments()
		self.assertEqual(len(comments), 2)
		self.assertIn("revoked", comments[1])
		self.assertIn(self.target, comments[1])

	def test_granting_twice_keeps_one_row_and_one_comment(self):
		as_user(self.admin, set_compliance_member, self.target, True)
		as_user(self.admin, set_compliance_member, self.target, True)
		rows = frappe.db.count("Has Role", {"parent": self.target, "role": COMPLIANCE_ROLE})
		self.assertEqual(rows, 1)
		self.assertEqual(len(self.new_comments()), 1)

	def test_revoking_a_user_without_the_role_changes_nothing(self):
		as_user(self.admin, set_compliance_member, self.target, False)
		self.assertEqual(self.new_comments(), [])

	def test_a_system_manager_cannot_grant_themselves(self):
		with self.assertRaises(frappe.PermissionError):
			as_user(self.admin, set_compliance_member, self.admin, True)
		self.assertFalse(has_explicit_role(self.admin, COMPLIANCE_ROLE))
		self.assertEqual(self.new_comments(), [])

	def test_self_revoke_is_refused_too(self):
		frappe.get_doc("User", self.admin).add_roles(COMPLIANCE_ROLE)
		with self.assertRaises(frappe.PermissionError):
			as_user(self.admin, set_compliance_member, self.admin, False)
		self.assertTrue(has_explicit_role(self.admin, COMPLIANCE_ROLE))

	def test_a_user_who_is_not_a_system_manager_is_refused(self):
		sales_manager = make_user("pdr.salesman@example.com", roles=["Sales Manager"])
		for caller in (sales_manager, self.target):
			with self.assertRaises(frappe.PermissionError):
				as_user(caller, set_compliance_member, self.target, True)
		self.assertFalse(has_explicit_role(self.target, COMPLIANCE_ROLE))
		self.assertEqual(self.new_comments(), [])

	def test_a_compliance_member_cannot_add_another_member(self):
		dana = make_user("pdr.dana2@example.com", roles=[COMPLIANCE_ROLE])
		with self.assertRaises(frappe.PermissionError):
			as_user(dana, set_compliance_member, self.target, True)
		self.assertFalse(has_explicit_role(self.target, COMPLIANCE_ROLE))

	def test_a_disabled_user_cannot_be_granted(self):
		off = make_user("pdr.off@example.com", roles=["Sales User"], enabled=0)
		with self.assertRaises(frappe.ValidationError):
			as_user(self.admin, set_compliance_member, off, True)
		self.assertFalse(has_explicit_role(off, COMPLIANCE_ROLE))

	def test_an_unknown_user_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			as_user(self.admin, set_compliance_member, "nobody.here@example.com", True)


def make_profiled_user(email: str, profile_roles: list[str]) -> str:
	"""A user whose roles come from a Role Profile: every save re-derives them from the profile."""
	profile = frappe.get_doc(
		{
			"doctype": "Role Profile",
			"role_profile": f"PDR profile {frappe.generate_hash(length=6)}",
			"roles": [{"role": role} for role in profile_roles],
		}
	).insert(ignore_permissions=True)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"role_profiles": [{"role_profile": profile.name}],
		}
	)
	user.insert(ignore_permissions=True)
	return user.name


class TestRoleProfileTargets(IntegrationTestCase):
	"""A save re-derives roles from the Role Profile, so a grant or revoke would be undone: refuse it up front."""

	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		self.admin = make_user("pdr.sysman2@example.com", roles=["System Manager"])
		self.before = len(audit_comments())

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def no_comment_written(self):
		self.assertEqual(audit_comments()[self.before :], [])

	def test_a_grant_to_a_role_profile_user_raises_and_changes_nothing(self):
		target = make_profiled_user("pdr.profiled.sales@example.com", ["Sales User"])
		roles_before = sorted(frappe.get_roles(target))
		with self.assertRaises(frappe.ValidationError) as caught:
			as_user(self.admin, set_compliance_member, target, True)
		self.assertIn("Role Profile", str(caught.exception))
		self.assertFalse(has_explicit_role(target, COMPLIANCE_ROLE))
		self.assertEqual(sorted(frappe.get_roles(target)), roles_before)
		self.no_comment_written()

	def test_a_revoke_from_a_role_profile_user_raises_and_the_role_stays(self):
		target = make_profiled_user("pdr.profiled.compliance@example.com", ["Sales User", COMPLIANCE_ROLE])
		self.assertTrue(has_explicit_role(target, COMPLIANCE_ROLE))
		with self.assertRaises(frappe.ValidationError):
			as_user(self.admin, set_compliance_member, target, False)
		self.assertTrue(has_explicit_role(target, COMPLIANCE_ROLE))
		self.no_comment_written()

	def test_a_change_that_did_not_take_effect_is_not_reported(self):
		target = make_user("pdr.silent@example.com", roles=["Sales User"])
		with (
			patch("frappe.core.doctype.user.user.User.add_roles", lambda self, *roles: None),
			self.assertRaises(frappe.ValidationError),
		):
			as_user(self.admin, set_compliance_member, target, True)
		self.assertFalse(has_explicit_role(target, COMPLIANCE_ROLE))
		self.no_comment_written()


class TestStandardUsers(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		self.admin = make_user("pdr.sysman3@example.com", roles=["System Manager"])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_administrator_and_guest_cannot_be_made_members(self):
		for user in ("Administrator", "Guest"):
			with self.subTest(user=user), self.assertRaises(frappe.ValidationError):
				as_user(self.admin, set_compliance_member, user, True)
			self.assertFalse(has_explicit_role(user, COMPLIANCE_ROLE))

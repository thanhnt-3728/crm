import frappe
from frappe.tests import IntegrationTestCase

from crm.api.session import get_session_role_flags
from crm.privacy import compliance_users, personal_fields
from crm.privacy.notify import notify
from crm.privacy.setup import DEFAULT_PERSONAL_FIELDS, ensure_privacy_setup

COMPLIANCE_USER = "privacy-compliance@example.com"
NOTIFIED_USER = "c1@example.com"


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles(*roles)


class TestPrivacySetup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		make_user(COMPLIANCE_USER, ["Sales User", "Compliance"])
		make_user(NOTIFIED_USER, ["Sales User"])

	def test_role_exists(self):
		ensure_privacy_setup()
		self.assertTrue(frappe.db.exists("Role", "Compliance"))

	def test_default_personal_fields_seeded_once(self):
		ensure_privacy_setup()
		ensure_privacy_setup()
		self.assertIn("linkedin", personal_fields("CRM Lead"))
		self.assertIn("designation", personal_fields("Contact"))
		rows = frappe.get_single("CRM Privacy Settings").personal_fields
		self.assertEqual(len(rows), sum(len(v) for v in DEFAULT_PERSONAL_FIELDS.values()))

	def test_hash_secret_generated(self):
		ensure_privacy_setup()
		self.assertTrue(frappe.get_single("CRM Privacy Settings").get_password("hash_secret"))

	def test_hash_secret_not_regenerated(self):
		ensure_privacy_setup()
		first = frappe.get_single("CRM Privacy Settings").get_password("hash_secret")
		ensure_privacy_setup()
		self.assertEqual(frappe.get_single("CRM Privacy Settings").get_password("hash_secret"), first)

	def test_compliance_users_lists_enabled_holders(self):
		self.assertIn(COMPLIANCE_USER, compliance_users())
		self.assertNotIn(NOTIFIED_USER, compliance_users())

	def test_session_flag_is_compliance(self):
		# user with Sales User + Compliance
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user(COMPLIANCE_USER)
		self.assertTrue(get_session_role_flags()["is_compliance"])
		frappe.set_user(NOTIFIED_USER)
		self.assertFalse(get_session_role_flags()["is_compliance"])

	def test_notify_creates_crm_notification_and_email(self):
		notify([NOTIFIED_USER], "Subject", "Body", request="PDR-0001")
		self.assertTrue(frappe.db.exists("CRM Notification", {"to_user": NOTIFIED_USER, "type": "Privacy"}))
		self.assertTrue(frappe.db.exists("Email Queue", {"message": ["like", "%Body%"]}))

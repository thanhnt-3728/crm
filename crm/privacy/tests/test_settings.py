import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.identifiers import (
	add_do_not_contact,
	compliance_users,
	get_secret,
	is_blocked,
	personal_fields,
)
from crm.privacy.install import after_migrate
from crm.privacy.rules import DEFAULT_PERSONAL_FIELDS


class TestPrivacySettings(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_role_and_seed(self):
		after_migrate()
		self.assertTrue(frappe.db.exists("Role", "Compliance"))
		self.assertEqual(personal_fields()["CRM Lead"], set(DEFAULT_PERSONAL_FIELDS["CRM Lead"]))

	def test_seed_does_not_readd_removed_rows(self):
		after_migrate()
		s = frappe.get_single("CRM Privacy Settings")
		s.personal_fields = [r for r in s.personal_fields if r.fieldname != "gender"]
		s.save()
		after_migrate()
		self.assertNotIn("gender", personal_fields()["CRM Lead"])

	def test_secret_generated_once(self):
		self.assertEqual(get_secret(), get_secret())
		self.assertEqual(len(get_secret()), 64)

	def test_saving_settings_keeps_secret(self):
		s = get_secret()
		settings = frappe.get_single("CRM Privacy Settings")
		settings.contract_retention_months = 12
		settings.save(ignore_permissions=True)
		self.assertEqual(get_secret(), s)

	def test_do_not_contact_survives_settings_save(self):
		add_do_not_contact("Email", "marisol@example.com", "PDR-0004")
		settings = frappe.get_single("CRM Privacy Settings")
		settings.contract_retention_months = 12
		settings.save(ignore_permissions=True)
		self.assertTrue(is_blocked("Email", "marisol@example.com"))

	def test_do_not_contact_roundtrip_any_format(self):
		add_do_not_contact("Phone", "(530) 555-0142", "PDR-0001")
		add_do_not_contact("Phone", "530.555.0142", "PDR-0001")
		self.assertEqual(frappe.db.count("CRM Do Not Contact"), 1)
		self.assertTrue(is_blocked("Phone", "+1 530 555 0142"))
		self.assertFalse(is_blocked("Phone", "530-555-0100"))
		row = frappe.get_last_doc("CRM Do Not Contact")
		self.assertNotIn("5550142", frappe.as_json(row.as_dict()))

	def test_do_not_contact_email_case_insensitive(self):
		add_do_not_contact("Email", " Marisol@Example.com ", "PDR-0002")
		self.assertTrue(is_blocked("Email", "marisol@example.com"))
		self.assertFalse(is_blocked("Email", "other@example.com"))

	def test_empty_value_is_not_blocked_and_not_added(self):
		before = frappe.db.count("CRM Do Not Contact")
		add_do_not_contact("Email", "  ", "PDR-0003")
		self.assertEqual(frappe.db.count("CRM Do Not Contact"), before)
		self.assertFalse(is_blocked("Email", ""))
		self.assertFalse(is_blocked("Phone", None))

	def test_compliance_users(self):
		after_migrate()
		email = "privacy-compliance-test@example.com"
		disabled = "privacy-compliance-disabled@example.com"
		for e, enabled in ((email, 1), (disabled, 0)):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": e,
					"first_name": "Priv",
					"enabled": enabled,
					"send_welcome_email": 0,
					"roles": [{"role": "Compliance"}],
				}
			).insert(ignore_permissions=True)
		users = compliance_users()
		self.assertIn(email, users)
		self.assertNotIn(disabled, users)
		self.assertNotIn("Administrator", users)
		self.assertNotIn("Guest", users)

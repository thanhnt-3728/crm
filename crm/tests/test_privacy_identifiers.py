# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.identifiers import (
	add_do_not_contact,
	extract_emails,
	is_do_not_contact,
	normalize,
	normalize_email,
	scramble,
	text_contains_email,
	text_contains_phone,
)
from crm.privacy.setup import ensure_privacy_setup


class TestPrivacyIdentifiers(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()

	def setUp(self):
		frappe.db.delete("CRM Do Not Contact")
		# Phone numbers below are typed without a country code, so the site region must be US.
		frappe.db.set_single_value("System Settings", "country", "United States")

	def test_normalize(self):
		self.assertEqual(normalize_email("  A@B.com "), "a@b.com")
		self.assertEqual(normalize_email(""), "")
		self.assertEqual(normalize("Email", " A@B.com "), "a@b.com")
		self.assertEqual(normalize("Phone", "(916) 555-0100"), "+19165550100")

	def test_scramble_is_keyed_and_normalized(self):
		self.assertEqual(scramble("Email", "A@B.com "), scramble("Email", "a@b.com"))
		self.assertNotEqual(scramble("Email", "a@b.com"), scramble("Phone", "a@b.com"))
		self.assertEqual(len(scramble("Email", "a@b.com")), 64)

	def test_email_case_insensitive(self):
		add_do_not_contact("Email", " Marisol.Vega@Example.net ")
		self.assertTrue(is_do_not_contact("Email", "marisol.vega@example.net"))

	def test_phone_formats(self):
		add_do_not_contact("Phone", "(916) 555-0100")
		for v in ["916.555.0100", "+19165550100", "+1 916 555 0100"]:
			self.assertTrue(is_do_not_contact("Phone", v), v)

	def test_not_listed(self):
		add_do_not_contact("Email", "a@b.com")
		self.assertFalse(is_do_not_contact("Email", "other@b.com"))
		self.assertFalse(is_do_not_contact("Phone", "a@b.com"))
		self.assertFalse(is_do_not_contact("Email", ""))

	def test_stores_no_plaintext(self):
		add_do_not_contact("Email", "a@b.com")
		self.assertFalse(frappe.db.exists("CRM Do Not Contact", {"value_hash": ["like", "%a@b.com%"]}))
		self.assertEqual(len(frappe.db.get_value("CRM Do Not Contact", {"kind": "Email"}, "value_hash")), 64)

	def test_idempotent(self):
		add_do_not_contact("Email", "a@b.com")
		add_do_not_contact("Email", "A@B.com")
		self.assertEqual(frappe.db.count("CRM Do Not Contact", {"kind": "Email"}), 1)

	def test_extract_emails(self):
		self.assertEqual(
			extract_emails('"Marisol Vega" <Marisol.Vega@x.net>, bob@x.net'),
			["marisol.vega@x.net", "bob@x.net"],
		)
		self.assertEqual(extract_emails(""), [])

	def test_text_contains_email(self):
		self.assertTrue(text_contains_email('{"email": "Marisol.Vega@X.net"}', "marisol.vega@x.net"))
		self.assertFalse(text_contains_email('{"email": "bob@x.net"}', "marisol.vega@x.net"))
		self.assertFalse(text_contains_email("", "marisol.vega@x.net"))
		self.assertFalse(text_contains_email("anything", ""))

	def test_text_contains_phone(self):
		self.assertTrue(text_contains_phone('{"mobile_no": "(916) 555-0100"}', "+19165550100"))
		self.assertTrue(text_contains_phone("call 916.555.0100 today", "916-555-0100"))
		self.assertFalse(text_contains_phone("call 916 555 0199", "+19165550100"))
		self.assertFalse(text_contains_phone("", "+19165550100"))
		self.assertFalse(text_contains_phone("call 916 555 0100", ""))

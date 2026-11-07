from frappe.tests import UnitTestCase

from crm.privacy.identifiers import hash_identifier, normalize_email, normalize_identifier


class TestIdentifiers(UnitTestCase):
	def test_email_lowercased_and_trimmed(self):
		self.assertEqual(normalize_email("  Marisol@SierraFoothills.example "), "marisol@sierrafoothills.example")

	def test_phone_formats_normalize_equal(self):
		forms = ["(530) 555-0142", "530.555.0142", "+1 530 555 0142", "5305550142"]
		self.assertEqual({normalize_identifier("Phone", f) for f in forms}, {"+15305550142"})

	def test_empty(self):
		self.assertEqual(normalize_identifier("Email", None), "")
		self.assertEqual(normalize_identifier("Phone", "  "), "")

	def test_hash_is_keyed_and_kind_scoped(self):
		h = hash_identifier("Email", "a@b.example", "s1")
		self.assertEqual(len(h), 64)
		self.assertNotEqual(h, hash_identifier("Email", "a@b.example", "s2"))
		self.assertNotEqual(h, hash_identifier("Phone", "a@b.example", "s1"))

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Identifier normalization, keyed hashing, validation and placeholder text (design 5.9). No DB."""

import hashlib
import hmac
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from crm.privacy.identifiers import (
	hash_identifier,
	normalize_email,
	normalize_identifier,
	validate_identifier,
)
from crm.privacy.placeholders import erased_content, erased_file, erased_person

SECRET = "a" * 64
US = patch("crm.utils.get_default_region", return_value="US")


class NormalizeTest(UnitTestCase):
	def test_email_is_trimmed_and_lowercased(self):
		self.assertEqual(normalize_email("  Jane.Doe@Example.COM \n"), "jane.doe@example.com")

	def test_empty_email_is_empty(self):
		self.assertEqual(normalize_email(None), "")
		self.assertEqual(normalize_email("   "), "")

	def test_phone_formats_normalize_to_the_same_e164(self):
		forms = ["+1 (415) 555-2671", "415-555-2671", "1 415 555 2671", "(415) 555.2671"]
		with US:
			self.assertEqual({normalize_identifier("phone", f) for f in forms}, {"+14155552671"})

	def test_email_kind_uses_email_normalization(self):
		self.assertEqual(normalize_identifier("email", " A@B.com "), "a@b.com")

	def test_unknown_kind_is_rejected(self):
		with self.assertRaises(ValueError):
			normalize_identifier("fax", "123")


class HashTest(UnitTestCase):
	def test_email_case_and_whitespace_give_the_same_hash(self):
		a = hash_identifier("email", "Jane@Example.com ", SECRET)
		b = hash_identifier("email", "jane@example.com", SECRET)
		self.assertEqual(a, b)
		self.assertEqual(len(a), 64)

	def test_phone_formats_give_the_same_hash(self):
		with US:
			a = hash_identifier("phone", "+1 415 555 2671", SECRET)
			b = hash_identifier("phone", "(415) 555-2671", SECRET)
		self.assertEqual(a, b)

	def test_different_secret_gives_a_different_hash(self):
		self.assertNotEqual(
			hash_identifier("email", "a@b.com", SECRET),
			hash_identifier("email", "a@b.com", "b" * 64),
		)

	def test_different_values_give_different_hashes(self):
		self.assertNotEqual(
			hash_identifier("email", "a@b.com", SECRET), hash_identifier("email", "c@b.com", SECRET)
		)

	def test_same_text_as_email_and_phone_differs(self):
		self.assertNotEqual(
			hash_identifier("email", "+14155552671", SECRET),
			hash_identifier("phone", "+14155552671", SECRET),
		)

	def test_phone_hash_does_not_depend_on_the_site_country(self):
		# National-format numbers are always read as US (CCPA), so changing System Settings
		# country later cannot change a hash and silently drop a block.
		hashes = set()
		for region in ("IN", "US", "GB"):
			with patch("crm.utils.get_default_region", return_value=region):
				hashes.add(hash_identifier("phone", "415-555-2671", SECRET))
				hashes.add(hash_identifier("phone", "(415) 555-2671", SECRET))
		hashes.add(hash_identifier("phone", "+14155552671", SECRET))
		self.assertEqual(len(hashes), 1)

	def test_known_vector(self):
		expected = hmac.new(b"k", b"email:a@b.com", hashlib.sha256).hexdigest()
		self.assertEqual(hash_identifier("email", "A@B.com", "k"), expected)

	def test_missing_secret_is_rejected(self):
		with self.assertRaises(ValueError):
			hash_identifier("email", "a@b.com", "")

	def test_empty_value_is_rejected(self):
		with self.assertRaises(ValueError):
			hash_identifier("email", "  ", SECRET)


class ValidateIdentifierTest(UnitTestCase):
	def test_valid_email_passes(self):
		validate_identifier("email", "jane@example.com")

	def test_bad_emails_raise(self):
		for bad in ["", "   ", "jane", "jane@", "@example.com", "jane@example", "ja ne@example.com"]:
			with self.subTest(bad=bad), self.assertRaises(frappe.ValidationError):
				validate_identifier("email", bad)

	def test_valid_phone_passes(self):
		with US:
			validate_identifier("phone", "(415) 555-2671")

	def test_short_or_empty_phones_raise(self):
		with US:
			for bad in ["", "12345", "abc", "+1 23 45"]:
				with self.subTest(bad=bad), self.assertRaises(frappe.ValidationError):
					validate_identifier("phone", bad)

	def test_unknown_kind_raises(self):
		with self.assertRaises(frappe.ValidationError):
			validate_identifier("fax", "1234567")

	def test_phone_validation_does_not_depend_on_the_site_country(self):
		for region in ("IN", "US"):
			with patch("crm.utils.get_default_region", return_value=region):
				validate_identifier("phone", "(415) 555-2671")


class PlaceholderTest(UnitTestCase):
	def test_placeholders_embed_the_request_number(self):
		self.assertEqual(erased_person("PDR-0001"), "Erased person PDR-0001")
		self.assertEqual(erased_content("PDR-0001"), "Content erased PDR-0001")
		self.assertEqual(erased_file("PDR-0001"), "File erased PDR-0001")

	def test_accepts_a_document_with_a_name(self):
		doc = frappe._dict(name="PDR-0042")
		self.assertEqual(erased_person(doc), "Erased person PDR-0042")
		self.assertEqual(erased_content(doc), "Content erased PDR-0042")
		self.assertEqual(erased_file(doc), "File erased PDR-0042")

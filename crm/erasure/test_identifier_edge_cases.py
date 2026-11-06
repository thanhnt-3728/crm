# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Edge cases found in review: site region, Italian leading zero, address boundaries, extensions"""

import unittest
from unittest.mock import patch

import frappe

from crm.erasure.discovery import diff_matches
from crm.erasure.identifiers import Identifiers, identifier_rows, normalize_phone_identifier


def ids(emails=("ann@x.com",), phones=()):
	return Identifiers.from_rows(identifier_rows(list(emails), list(phones), region="US"), region="US")


def site_country(country):
	"""Patch System Settings.country as the erasure path reads it"""
	real = frappe.db.get_single_value

	def fake(doctype, field, *args, **kwargs):
		if (doctype, field) == ("System Settings", "country"):
			return country
		return real(doctype, field, *args, **kwargs)

	return patch.object(frappe.db, "get_single_value", side_effect=fake)


class TestSiteRegion(unittest.TestCase):
	def test_without_site_country_a_number_needs_its_country_code(self):
		with site_country(None):
			for value in ("(415) 555-0123", "4155550123", "98765 43210"):
				with self.subTest(value=value), self.assertRaises(ValueError) as caught:
					normalize_phone_identifier(value)
				self.assertIn("country code", str(caught.exception))
			self.assertEqual(normalize_phone_identifier("+1 (415) 555-0123"), "+14155550123")
			self.assertEqual(normalize_phone_identifier("0044 20 7946 0958"), "+442079460958")

	def test_with_site_country_its_region_applies(self):
		with site_country("United States"):
			self.assertEqual(normalize_phone_identifier("(415) 555-0123"), "+14155550123")

	def test_other_country_code_does_not_match(self):
		her = ids(emails=(), phones=("+1 415-555-0123",))
		self.assertFalse(her.matches_phone("+91 415 555 0123"))
		self.assertTrue(her.matches_phone("+1 415 555 0123"))


class TestItalianLeadingZero(unittest.TestCase):
	def test_national_significant_number_keeps_the_zero(self):
		her = ids(emails=(), phones=("+39 06 1234 5678",))
		self.assertEqual(her.search_digits, ("0612345678",))
		for spelling in ("+390612345678", "0039 06 12345678", "+39 06 1234 5678", "06 1234 5678"):
			with self.subTest(spelling=spelling):
				self.assertTrue(her.matches_phone(spelling))
				self.assertTrue(her.matches_text(f"call {spelling} today"))
		self.assertFalse(her.matches_phone("+39 06 1234 5679"))


class TestAddressBoundaries(unittest.TestCase):
	PREFIXED = ("=", "#", "!", "/", "&", "é", "+", "'", "%", "~", "_", ".")

	def test_a_longer_address_ending_in_hers_never_matches(self):
		her = ids()
		for char in self.PREFIXED:
			value = f"jo{char}ann@x.com"
			with self.subTest(value=value):
				self.assertFalse(her.matches_email(value))
				self.assertFalse(her.matches_email(f"Kai <kai@y.com>, {value}"))
				self.assertFalse(her.matches_text(f"from {value} today"))

	def test_address_lists_and_quoted_text_still_match(self):
		her = ids()
		self.assertTrue(her.matches_email('"Lee, Ann" <Ann@X.com>; bob@y.com'))
		self.assertTrue(her.matches_email("kai@y.com\nann@x.com"))
		self.assertTrue(her.matches_text("{'email': 'ann@x.com'}"))  # Python repr in a traceback
		self.assertTrue(her.matches_text("mailto:ann@x.com."))
		self.assertFalse(her.matches_text("o'ann@x.com"))
		self.assertFalse(her.matches_text("ann@x.com.au"))


class TestExtensions(unittest.TestCase):
	def test_extension_is_kept_in_the_normalized_value(self):
		self.assertEqual(normalize_phone_identifier("+1 415 555 0123 x12"), "+14155550123;ext=12")
		self.assertEqual(normalize_phone_identifier("+14155550123;ext=12"), "+14155550123;ext=12")

	def test_extensions_must_agree_when_both_sides_have_one(self):
		hers = ids(emails=(), phones=("+1 415-555-0123 x12",))
		for value in ("(415) 555-0123", "(415) 555-0123 x12", "+1 415 555 0123 ext. 12", "4155550123;ext=12"):
			with self.subTest(value=value):
				self.assertTrue(hers.matches_phone(value))
		for value in ("(415) 555-0123 x45", "+1 415 555 0123 ext 45"):
			with self.subTest(value=value):
				self.assertFalse(hers.matches_phone(value))
		no_extension = ids(emails=(), phones=("+1 415-555-0123",))
		self.assertTrue(no_extension.matches_phone("(415) 555-0123 x45"))


class TestDiffMatchesFreshness(unittest.TestCase):
	def test_rows_still_found_take_reason_and_action_from_discovery(self):
		stored = [
			{"ref_doctype": "Address", "ref_name": "A1", "reason": "linked", "action": "scrub", "excluded": 1}
		]
		current = [{"ref_doctype": "Address", "ref_name": "A1", "reason": "email", "action": "unlink"}]
		[row] = diff_matches(stored, current)
		self.assertEqual((row["reason"], row["action"], row["excluded"]), ("email", "unlink", 1))

	def test_missing_rows_can_be_dropped(self):
		stored = [
			{"ref_doctype": "Comment", "ref_name": "C1", "reason": "activity", "action": "replace_content"}
		]
		self.assertEqual(diff_matches(stored, [], keep_missing=False), [])

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
import unittest

from crm.erasure.discovery import diff_matches
from crm.erasure.identifiers import (
	Identifiers,
	identifier_rows,
	normalize_email,
	normalize_phone_identifier,
)

HER_PHONE_SPELLINGS = (
	"(415) 555-0123",
	"+1 415-555-0123",
	"4155550123",
	"001 415 555 0123",
	"1-415-555-0123",
	"415.555.0123",
	"+14155550123",
)


def ids(emails=("ann@x.com",), phones=("+1 415-555-0123",)):
	return Identifiers.from_rows(identifier_rows(list(emails), list(phones), region="US"), region="US")


class TestNormalizeIdentifiers(unittest.TestCase):
	def test_email_is_lowercased_and_trimmed(self):
		self.assertEqual(normalize_email("  Ann.Lee@Example.COM "), "ann.lee@example.com")

	def test_invalid_or_empty_email_is_rejected(self):
		for value in ("", "   ", None, "ann", "ann@", "@x.com", "ann@x", "a b@x.com", "Ann <ann@x.com>"):
			with self.subTest(value=value), self.assertRaises(ValueError):
				normalize_email(value)

	def test_phone_spellings_normalize_to_one_e164(self):
		for spelling in HER_PHONE_SPELLINGS:
			with self.subTest(spelling=spelling):
				self.assertEqual(normalize_phone_identifier(spelling, region="US"), "+14155550123")

	def test_empty_short_or_invalid_phone_is_rejected(self):
		for value in ("", "  ", None, "abc", "12-34", "+999 999", "555-0100"):
			with self.subTest(value=value), self.assertRaises(ValueError):
				normalize_phone_identifier(value, region="US")

	def test_identifier_rows_dedupe_on_normalized_value(self):
		rows = identifier_rows(["Ann@x.com", "ann@x.com "], ["(415) 555-0123", "+14155550123"], region="US")
		self.assertEqual(
			rows,
			[
				{"kind": "Email", "value": "Ann@x.com", "normalized": "ann@x.com"},
				{"kind": "Phone", "value": "(415) 555-0123", "normalized": "+14155550123"},
			],
		)

	def test_identifier_rows_reject_an_invalid_value_without_echoing_it(self):
		with self.assertRaises(ValueError) as caught:
			identifier_rows(["ann@x.com", "secret-not-an-email"], [], region="US")
		self.assertNotIn("secret", str(caught.exception))

	def test_from_rows_uses_stored_normalized_or_the_value(self):
		found = Identifiers.from_rows(
			[
				{"kind": "Email", "value": "Ann@X.com", "normalized": None},
				{"kind": "Phone", "value": "(415) 555-0123", "normalized": "+14155550123"},
			],
			region="US",
		)
		self.assertEqual(found.emails, frozenset({"ann@x.com"}))
		self.assertEqual([p.e164 for p in found.phones], ["+14155550123"])
		self.assertEqual(found.search_digits, ("4155550123",))


class TestMatching(unittest.TestCase):
	def test_email_match_is_exact_and_case_insensitive(self):
		her = ids()
		for value in ("ann@x.com", "ANN@X.COM", "Ann Lee <Ann@x.com>", "bob@y.com, ann@x.com; c@z.com"):
			with self.subTest(value=value):
				self.assertTrue(her.matches_email(value))
		for value in ("joann@x.com", "ann@x.com.au", "mary.ann@x.com", "ann@xx.com", "", None, "ann x.com"):
			with self.subTest(value=value):
				self.assertFalse(her.matches_email(value))

	def test_phone_matches_every_spelling(self):
		her = ids()
		for spelling in HER_PHONE_SPELLINGS:
			with self.subTest(spelling=spelling):
				self.assertTrue(her.matches_phone(spelling))

	def test_phone_near_misses_do_not_match(self):
		her = ids()
		for value in (
			"(415) 555-0124",
			"+44 415 555 0123",
			"41555501234",
			"+1 415 555 012",
			"",
			None,
			"0123",
		):
			with self.subTest(value=value):
				self.assertFalse(her.matches_phone(value))

	def test_text_scan_finds_identifiers_inside_json_and_prose(self):
		her = ids()
		version = json.dumps({"changed": [["mobile_no", None, "14155550123"]]})
		self.assertTrue(her.matches_text(version))
		self.assertTrue(her.matches_text('{"from": "Ann <ANN@x.com>"}'))
		self.assertTrue(her.matches_text("Call me on (415) 555-0123 after 5"))
		self.assertTrue(her.matches_text("&lt;ann@x.com&gt;"))

	def test_text_scan_ignores_near_misses(self):
		her = ids()
		self.assertFalse(her.matches_text("joann@x.com called from (415) 555-0124 at 2026-11-05 10:00"))
		self.assertFalse(her.matches_text(""))
		self.assertFalse(her.matches_text(None))

	def test_no_identifiers_match_nothing(self):
		nobody = Identifiers.from_rows([], region="US")
		self.assertFalse(nobody.matches_text("ann@x.com 4155550123"))


class TestDiffMatches(unittest.TestCase):
	def test_new_rows_are_flagged_and_stored_rows_keep_their_flags(self):
		stored = [
			{
				"ref_doctype": "CRM Lead",
				"ref_name": "L1",
				"reason": "linked",
				"action": "scrub",
				"excluded": 0,
			},
			{
				"ref_doctype": "Communication",
				"ref_name": "C1",
				"reason": "email",
				"action": "replace_content",
				"excluded": 1,
				"new_since_logging": 0,
			},
		]
		current = [
			{"ref_doctype": "CRM Lead", "ref_name": "L1", "reason": "linked", "action": "scrub"},
			{
				"ref_doctype": "Communication",
				"ref_name": "C1",
				"reason": "email",
				"action": "replace_content",
			},
			{
				"ref_doctype": "Communication",
				"ref_name": "C2",
				"reason": "phone",
				"action": "replace_content",
			},
		]
		rows = diff_matches(stored, current)
		by_key = {(r["ref_doctype"], r["ref_name"]): r for r in rows}
		self.assertEqual(len(rows), 3)
		self.assertEqual(by_key[("CRM Lead", "L1")]["new_since_logging"], 0)
		self.assertEqual(by_key[("Communication", "C1")]["excluded"], 1)
		self.assertEqual(by_key[("Communication", "C1")]["new_since_logging"], 0)
		self.assertEqual(by_key[("Communication", "C2")]["new_since_logging"], 1)
		self.assertEqual(by_key[("Communication", "C2")]["excluded"], 0)

	def test_stored_rows_no_longer_found_are_kept(self):
		stored = [
			{"ref_doctype": "FCRM Note", "ref_name": "N1", "reason": "activity", "action": "replace_content"}
		]
		rows = diff_matches(stored, [])
		self.assertEqual([(r["ref_doctype"], r["ref_name"]) for r in rows], [("FCRM Note", "N1")])

	def test_nothing_new_flags_nothing_and_never_duplicates(self):
		row = {"ref_doctype": "CRM Lead", "ref_name": "L1", "reason": "linked", "action": "scrub"}
		rows = diff_matches([row], [row, dict(row)])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["new_since_logging"], 0)

	def test_rows_carry_only_match_keys(self):
		row = {
			"ref_doctype": "CRM Lead",
			"ref_name": "L1",
			"reason": "linked",
			"action": "scrub",
			"name": "row-1",
			"idx": 1,
			"parent": "CRM-ERQ-2026-00001",
		}
		self.assertEqual(
			set(diff_matches([row], [])[0]),
			{"ref_doctype", "ref_name", "reason", "action", "excluded", "new_since_logging"},
		)

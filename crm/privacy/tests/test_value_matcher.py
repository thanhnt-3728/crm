# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Whole-value matching of her identifiers inside text (phase 05 step 2, RT-4). No DB."""

from unittest.mock import patch

from frappe.tests import UnitTestCase

from crm.privacy.erasure.value_matcher import (
	Identifiers,
	has_address,
	holds_her_value,
	holds_identifier,
	like_literal,
	parse_addresses,
	replace_addresses,
	same_phone,
)

PH = "Erased person PDR-0001"
HER = Identifiers.of(
	[("email", " M.Vega@Example.com "), ("Email", "marisol@gmail.example"), ("phone", "(530) 555-0101")]
)
US = patch("crm.utils.get_default_region", return_value="US")


def setUpModule():
	US.start()


def tearDownModule():
	US.stop()


class TestIdentifiers(UnitTestCase):
	def test_values_are_normalized_and_kinds_are_case_blind(self):
		self.assertEqual(HER.emails, {"m.vega@example.com", "marisol@gmail.example"})
		self.assertEqual(HER.phones, {"+15305550101"})

	def test_empty_values_are_dropped(self):
		self.assertFalse(Identifiers.of([("email", ""), ("phone", None), ("email", "  ")]))


class TestLikeLiteral(UnitTestCase):
	def test_percent_underscore_and_backslash_are_escaped(self):
		self.assertEqual(like_literal(r"a%b_c\d"), r"a\%b\_c\\d")

	def test_plain_text_is_unchanged(self):
		self.assertEqual(like_literal("m.vega@example.com"), "m.vega@example.com")


class TestAddressLists(UnitTestCase):
	LIST = "Marisol Vega <M.Vega@example.com>, jon.park@sierra.example.com; adam.vega@example.com"

	def test_parse_splits_on_commas_and_semicolons(self):
		self.assertEqual(
			[a for _name, a in parse_addresses(self.LIST)],
			["m.vega@example.com", "jon.park@sierra.example.com", "adam.vega@example.com"],
		)

	def test_whole_address_only(self):
		self.assertTrue(has_address(self.LIST, HER.emails))
		self.assertFalse(has_address("adam.vega@example.com", HER.emails))  # shares a suffix with hers
		self.assertFalse(has_address("xm.vega@example.com, m.vega@example.com.au", HER.emails))
		self.assertFalse(has_address("", HER.emails))
		self.assertFalse(has_address(None, HER.emails))

	def test_replacement_keeps_other_addresses_and_their_names(self):
		text = (
			"Marisol Vega <M.Vega@example.com>, Jon Park <jon.park@sierra.example.com>; adam.vega@example.com"
		)
		self.assertEqual(
			replace_addresses(text, HER.emails, PH),
			f"{PH}, Jon Park <jon.park@sierra.example.com>; adam.vega@example.com",
		)

	def test_replacement_of_a_list_without_her_changes_nothing(self):
		text = "jon.park@sierra.example.com, adam.vega@example.com"
		self.assertEqual(replace_addresses(text, HER.emails, PH), text)

	def test_replacement_of_a_lone_address(self):
		self.assertEqual(replace_addresses("m.vega@example.com", HER.emails, PH), PH)
		self.assertEqual(replace_addresses(None, HER.emails, PH), None)


class TestPhones(UnitTestCase):
	def test_any_format_matches_the_whole_number(self):
		for stored in ("+1 530 555 0101", "530-555-0101", "(530) 555-0101", " +15305550101 "):
			self.assertTrue(same_phone(stored, HER.phones), stored)

	def test_a_longer_number_containing_her_digits_does_not_match(self):
		for stored in ("+153055501019", "+1 530 555 01010", "9915305550101", "", None):
			self.assertFalse(same_phone(stored, HER.phones), stored)


class TestHoldsHerValue(UnitTestCase):
	def test_an_identifier_matches_with_case_and_spacing(self):
		self.assertTrue(holds_her_value("  M.VEGA@example.COM", HER))
		self.assertTrue(holds_her_value("530.555.0101".replace(".", "-"), HER))

	def test_the_same_field_on_a_confirmed_record_matches_case_blind(self):
		self.assertTrue(holds_her_value(" marisol ", HER, same_field_values=["Marisol", "Vega"]))
		self.assertFalse(holds_her_value("Jon", HER, same_field_values=["Marisol", "Vega"]))

	def test_a_colleague_or_empty_value_does_not_match(self):
		for value in ("jon.park@sierra.example.com", "+15305550177", "", None, "adam.vega@example.com"):
			self.assertFalse(holds_her_value(value, HER), value)

	def test_the_confirmed_value_is_matched_whole_not_as_a_part(self):
		self.assertFalse(holds_her_value("Marisol Vega-Jones", HER, same_field_values=["Marisol Vega"]))


class TestHoldsIdentifier(UnitTestCase):
	def test_a_whole_field_value_anywhere_in_the_document(self):
		doc = {"name": "X", "email": "M.Vega@Example.com", "phone_nos": [{"phone": "+1 530 555 0101"}]}
		self.assertTrue(holds_identifier(doc, HER))
		self.assertTrue(holds_identifier({"recipients": "Jon <jon@x.example>, m.vega@example.com"}, HER))

	def test_a_value_that_only_contains_hers_does_not_count(self):
		doc = {
			"email": "adam.vega@example.com",
			"phone": "+153055501019",
			"note": "write to m.vega@example.com",
		}
		self.assertFalse(holds_identifier(doc, HER))

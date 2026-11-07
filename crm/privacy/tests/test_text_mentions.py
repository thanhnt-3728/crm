# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Her identifiers and the request number inside free text: notifications, queued mail, raw email (RT-4, RT-10)."""

from unittest.mock import patch

from frappe.tests import UnitTestCase

from crm.privacy.erasure.text_mentions import mentions_identifier, mentions_number, prefilter_terms
from crm.privacy.erasure.value_matcher import Identifiers

HER = Identifiers.of([("email", "m.vega@example.com"), ("phone", "+1 530 555 0101")])
US = patch("crm.utils.get_default_region", return_value="US")


def setUpModule():
	US.start()


def tearDownModule():
	US.stop()


class TestMentionsIdentifier(UnitTestCase):
	def test_an_email_inside_text_or_markup(self):
		for text in (
			"New email from m.vega@example.com",
			"<b>M.Vega@Example.com</b> replied",
			"Contact m.vega@example.com.",
			"To: Marisol <m.vega@example.com>; jon@x.example",
			"m.vega@example.com",
		):
			self.assertTrue(mentions_identifier(text, HER), text)

	def test_a_longer_address_that_contains_hers_does_not_count(self):
		for text in (
			"adam.vega@example.com wrote",
			"m.vega@example.com.au",
			"xm.vega@example.com",
			"m.vega@example.community",
			"m.vega@example.com-old",
			"",
			None,
		):
			self.assertFalse(mentions_identifier(text, HER), text)

	def test_a_phone_in_any_format(self):
		for text in (
			"Missed call from +1 530 555 0101",
			"call (530) 555-0101 back",
			"number: 530.555.0101.",
			"+15305550101",
		):
			self.assertTrue(mentions_identifier(text, HER), text)

	def test_a_longer_number_that_contains_hers_does_not_count(self):
		for text in ("+153055501019", "call 9915305550101 now", "order 530555010", "ticket 15305550102"):
			self.assertFalse(mentions_identifier(text, HER), text)

	def test_no_identifiers_never_match(self):
		self.assertFalse(mentions_identifier("m.vega@example.com", Identifiers()))


class TestMentionsNumber(UnitTestCase):
	def test_the_whole_request_number(self):
		for text in ("PDR-0001: privacy erasure request", "see (PDR-0001)", "x PDR-0001", "PDR-0001"):
			self.assertTrue(mentions_number(text, "PDR-0001"), text)

	def test_another_request_with_the_same_start_does_not_count(self):
		for text in ("PDR-00010 is open", "PDR-0001234", "XPDR-0001", "pdr-1", "", None):
			self.assertFalse(mentions_number(text, "PDR-0001"), text)


class TestPrefilterTerms(UnitTestCase):
	def test_each_email_and_the_last_digits_of_each_phone(self):
		self.assertEqual(sorted(prefilter_terms(HER)), ["0101", "m.vega@example.com"])

	def test_nothing_for_no_identifiers(self):
		self.assertEqual(prefilter_terms(Identifiers()), [])

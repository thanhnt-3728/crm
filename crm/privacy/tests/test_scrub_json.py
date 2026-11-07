# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Her identifiers inside JSON text (sync logs): whole values only, anywhere in the document. No DB."""

import json
from unittest.mock import patch

from frappe.tests import UnitTestCase

from crm.privacy.erasure.scrub_json import blank_identifiers, blank_text_values
from crm.privacy.erasure.value_matcher import Identifiers

HER = Identifiers.of([("email", "m.vega@example.com"), ("phone", "+1 530 555 0101")])
PH = "Erased person PDR-0001"
US = patch("crm.utils.get_default_region", return_value="US")


def setUpModule():
	US.start()


def tearDownModule():
	US.stop()


class TestBlankIdentifiers(UnitTestCase):
	def test_values_that_are_hers_are_replaced_at_any_depth(self):
		data = {
			"email": "M.Vega@example.com",
			"field_data": [
				{"name": "phone", "values": ["(530) 555-0101"]},
				{"name": "city", "values": ["Chico"]},
			],
		}
		out = json.loads(blank_identifiers(json.dumps(data), HER, PH))
		self.assertEqual(out["email"], PH)
		self.assertEqual(out["field_data"][0]["values"], [PH])
		self.assertEqual(out["field_data"][1], {"name": "city", "values": ["Chico"]})

	def test_a_value_that_only_contains_hers_stays(self):
		data = {
			"email": "adam.vega@example.com",
			"note": "write to m.vega@example.com",
			"phone": "+153055501019",
		}
		self.assertEqual(json.loads(blank_identifiers(json.dumps(data), HER, PH)), data)

	def test_text_that_is_not_json_comes_back_as_it_was(self):
		for text in ("not json", "", None, '"m.vega@example.com"'):
			self.assertEqual(blank_identifiers(text, HER, PH), text)


class TestBlankTextValues(UnitTestCase):
	def test_every_text_is_replaced_and_keys_numbers_and_empty_texts_stay(self):
		data = {"full_name": "Marisol Vega", "email": "m.vega@example.com", "score": 3, "ok": True,
			"empty": "", "field_data": [{"name": "city", "values": ["Chico", "  "]}]}  # fmt: skip
		out = json.loads(blank_text_values(json.dumps(data), PH))
		self.assertEqual(out["full_name"], PH)
		self.assertEqual(out["email"], PH)
		self.assertEqual((out["score"], out["ok"], out["empty"]), (3, True, ""))
		self.assertEqual(out["field_data"], [{"name": PH, "values": [PH, "  "]}])

	def test_text_that_is_not_json_comes_back_as_it_was(self):
		for text in ("not json", "", None, '"Marisol Vega"'):
			self.assertEqual(blank_text_values(text, PH), text)

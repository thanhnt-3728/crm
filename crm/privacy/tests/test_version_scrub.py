# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Change history (Version data): her own records are wiped by field, everyone else's only by value (H1, H2)."""

import json
from unittest.mock import patch

from frappe.tests import UnitTestCase

from crm.privacy.erasure.value_matcher import Identifiers
from crm.privacy.erasure.version_scrub import VersionRules, scrub_version

HER = Identifiers.of([("email", "m.vega@example.com"), ("phone", "+1 530 555 0101")])
PH = "Erased person PDR-0001"
US = patch("crm.utils.get_default_region", return_value="US")
NAMES = frozenset({"Marisol Vega"})
PARTS = frozenset({"Marisol", "Vega"})
OWN = VersionRules(HER, PH, field_wise=frozenset({"email", "email_id", "full_name", "lead_name", "gender"}),
	names=NAMES, name_parts=PARTS)  # fmt: skip
SHARED = VersionRules(HER, PH, row_fields=frozenset({"full_name", "email", "mobile_no", "phone", "gender"}),
	names=NAMES, name_parts=PARTS, her_rows=lambda table, row: row.get("contact") == "Marisol Vega")  # fmt: skip
JOHN = {
	"contact": "John Doe",
	"full_name": "John Doe",
	"email": "john@acme.example",
	"mobile_no": "+12125550100",
}
SHE = {
	"contact": "Marisol Vega",
	"full_name": "Marisol Vega",
	"email": "m.vega@example.com",
	"gender": "Female",
}


def setUpModule():
	US.start()


def tearDownModule():
	US.stop()


def scrub(rules, data):
	out, changed = scrub_version(json.dumps(data), rules, PH)
	return json.loads(out), changed


class TestHerOwnRecords(UnitTestCase):
	def test_personal_fields_lose_both_values_and_the_rest_stays(self):
		data = {"changed": [["email", "old@x.example", "m.vega@example.com"], ["status", "Open", "Won"],
			["lead_name", "", "Marisol Vega"], ["gender", "", "Female"]]}  # fmt: skip
		out, changed = scrub(OWN, data)
		self.assertTrue(changed)
		self.assertEqual(
			out["changed"],
			[["email", PH, PH], ["status", "Open", "Won"], ["lead_name", "", PH], ["gender", "", PH]],
		)

	def test_added_removed_and_row_changed_rows(self):
		data = {"row_changed": [["email_ids", 0, "abc", [["email_id", "m.vega@example.com", ""], ["is_primary", 0, 1]]]],
			"added": [["email_ids", {"email_id": "marisol@gmail.example", "idx": 2}]],
			"removed": [["email_ids", {"email_id": "m.vega@example.com", "idx": 1}]]}  # fmt: skip
		out, _changed = scrub(OWN, data)
		self.assertEqual(out["row_changed"][0][3], [["email_id", PH, ""], ["is_primary", 0, 1]])
		self.assertEqual(out["added"][0][1], {"email_id": PH, "idx": 2})
		self.assertEqual(out["removed"][0][1], {"email_id": PH, "idx": 1})

	def test_a_value_that_is_hers_in_another_field_is_replaced(self):
		out, _changed = scrub(
			OWN, {"changed": [["description", "from m.vega@example.com", "m.vega@example.com"]]}
		)
		self.assertEqual(out["changed"], [["description", "from m.vega@example.com", PH]])


class TestSomeoneElsesRecords(UnitTestCase):
	def test_a_version_without_her_values_is_untouched_even_in_personal_looking_fields(self):
		data = {"changed": [["email", "john@acme.example", "jane@acme.example"], ["gender", "", "Female"],
			["salutation", "", "Ms"], ["job_title", "", "Practice manager"]],
			"added": [["contacts", JOHN]], "removed": [["contacts", {**JOHN, "idx": 3}]],
			"row_changed": [["contacts", 1, "row-john", [["email", "j@acme.example", "john@acme.example"]]]]}  # fmt: skip
		out, changed = scrub(SHARED, data)
		self.assertFalse(changed)
		self.assertEqual(out, data)

	def test_only_her_row_in_the_contacts_table_is_replaced(self):
		out, changed = scrub(
			SHARED, {"added": [["contacts", JOHN], ["contacts", SHE]], "removed": [["contacts", SHE]]}
		)
		self.assertTrue(changed)
		self.assertEqual(out["added"][0][1], JOHN)
		self.assertEqual(out["added"][1][1], {"contact": PH, "full_name": PH, "email": PH, "gender": PH})
		self.assertEqual(out["removed"][0][1]["full_name"], PH)

	def test_a_row_changed_entry_is_hers_when_its_row_is(self):
		rules = VersionRules(
			HER, PH, row_fields=SHARED.row_fields, her_rows=lambda t, row: row.get("name") == "row-she"
		)
		data = {"row_changed": [["contacts", 1, "row-she", [["email", "x@y.example", "z@y.example"]]],
			["contacts", 2, "row-john", [["email", "x@y.example", "z@y.example"]]]]}  # fmt: skip
		out, _changed = scrub(rules, data)
		self.assertEqual(out["row_changed"][0][3], [["email", PH, PH]])
		self.assertEqual(out["row_changed"][1][3], [["email", "x@y.example", "z@y.example"]])

	def test_her_values_in_a_top_level_change_are_replaced_by_value(self):
		data = {"changed": [["email", "john@acme.example", "m.vega@example.com"], ["mobile_no", "", "(530) 555-0101"],
			["lead_name", "", "Marisol Vega"], ["first_name", "", "Marisol"], ["job_title", "", "Marisol"]]}  # fmt: skip
		out, _changed = scrub(SHARED, data)
		self.assertEqual(
			out["changed"],
			[
				["email", "john@acme.example", PH],
				["mobile_no", "", PH],
				["lead_name", "", PH],
				["first_name", "", PH],
				["job_title", "", "Marisol"],
			],
		)  # a name field matches her name, a title does not

	def test_an_address_list_loses_only_her_address(self):
		value = "Marisol <m.vega@example.com>, jon.park@sierra.example.com"
		out, _changed = scrub(SHARED, {"changed": [["recipients", "", value]]})
		self.assertEqual(out["changed"], [["recipients", "", f"{PH}, jon.park@sierra.example.com"]])

	def test_text_that_mentions_her_is_replaced_whole_where_the_rules_say_so(self):
		rules = VersionRules(HER, PH, names=NAMES, mentions=True)
		out, _changed = scrub(
			rules, {"changed": [["subject", "Call with Marisol Vega", "Call"], ["subject", "", "Lunch"]]}
		)
		self.assertEqual(out["changed"], [["subject", PH, "Call"], ["subject", "", "Lunch"]])

	def test_a_version_with_nothing_of_hers_comes_back_as_the_same_text(self):
		raw = json.dumps({"changed": [["status", "Open", "Won"]], "creation": "2026-01-01"})
		self.assertEqual(scrub_version(raw, OWN, PH), (raw, False))

	def test_unparseable_data_comes_back_as_it_was(self):
		self.assertEqual(scrub_version("not json", OWN, PH), ("not json", False))

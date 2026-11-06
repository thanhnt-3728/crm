# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from crm.erasure.identifiers import Identifiers
from crm.erasure.registry_model import (
	CLEAR,
	CLEAR_IF_HERS,
	MARKER,
	MARKER_IF_HERS,
	NAME_MARKER,
	REMOVE_ADDRESS,
)
from crm.erasure.scrub_actions import (
	field_value,
	filter_version_data,
	scrub_address_list,
	version_is_empty,
)

HER = "marisol.vega@example.net"
IDS = Identifiers.from_rows([{"kind": "Email", "value": HER}, {"kind": "Phone", "value": "+14155550123"}])
REQ = "CRM-ERQ-2026-00001"


class TestScrubAddressList(UnitTestCase):
	def test_removes_her_address_whatever_its_case(self):
		value = "A <a@x>, Marisol <MARISOL.VEGA@example.net>"
		self.assertEqual(scrub_address_list(value, IDS), "A <a@x>")

	def test_keeps_colleagues_and_superstrings_unchanged(self):
		value = "Kai <kai@example.net>, jomarisol.vega@example.net"
		self.assertEqual(scrub_address_list(value, IDS), value)

	def test_only_her_address_clears_the_field(self):
		self.assertIsNone(scrub_address_list(f"Marisol <{HER}>", IDS))
		self.assertIsNone(scrub_address_list(None, IDS))

	def test_mixed_separators_and_idempotent(self):
		value = f"kai@example.net; {HER}\nrep@example.com"
		once = scrub_address_list(value, IDS)
		self.assertEqual(once, "kai@example.net, rep@example.com")
		self.assertEqual(scrub_address_list(once, IDS), once)


class TestFieldValue(UnitTestCase):
	def value(self, spec, **row):
		return field_value(spec, row, IDS, REQ)

	def test_markers_replace_only_present_values(self):
		self.assertEqual(self.value(("content", MARKER), content="Hi"), f"Content erased {REQ}")
		self.assertEqual(self.value(("first_name", NAME_MARKER), first_name="M"), f"Erased {REQ}")
		self.assertIsNone(self.value(("lost_notes", MARKER), lost_notes=None))
		self.assertIsNone(self.value(("email", CLEAR), email=HER))

	def test_if_hers_treatments_follow_the_deciding_column(self):
		spec = ("sender_full_name", CLEAR_IF_HERS, "sender")
		self.assertIsNone(self.value(spec, sender=f"M <{HER}>", sender_full_name="Marisol"))
		self.assertEqual(self.value(spec, sender="kai@example.net", sender_full_name="Kai"), "Kai")
		spec = ("from", MARKER_IF_HERS, "from")
		self.assertEqual(self.value(spec, **{"from": "(415) 555-0123"}), f"Erased {REQ}")
		self.assertEqual(self.value(spec, **{"from": "(415) 555-0124"}), "(415) 555-0124")

	def test_remove_address(self):
		spec = ("cc", REMOVE_ADDRESS)
		self.assertEqual(self.value(spec, cc=f"kai@example.net, {HER}"), "kai@example.net")


class TestVersionFilter(UnitTestCase):
	def test_drops_person_fields_her_rows_and_identifier_entries(self):
		data = {
			"changed": [
				["status", "Open", "Won"],
				["email", None, "anything"],
				["deal_value", 1, 2],
				["notes", None, "call +1 415 555 0123"],
			],
			"added": [["contacts", {"name": "her-row"}], ["contacts", {"name": "kai-row", "contact": "K"}]],
			"removed": [["contacts", {"name": "x", "email": HER}]],
			"row_changed": [
				["contacts", 1, "her-row", [["full_name", "a", "b"]]],
				["contacts", 2, "kai-row", [["is_primary", 0, 1], ["email", None, HER]]],
			],
			"comment": "kept as is",
		}
		kept = filter_version_data(data, frozenset({"email"}), IDS, {"her-row"})
		self.assertEqual(kept["changed"], [["status", "Open", "Won"], ["deal_value", 1, 2]])
		self.assertEqual(kept["added"], [["contacts", {"name": "kai-row", "contact": "K"}]])
		self.assertEqual(kept["removed"], [])
		self.assertEqual(kept["row_changed"], [["contacts", 2, "kai-row", [["is_primary", 0, 1]]]])
		self.assertEqual(kept["comment"], "kept as is")
		self.assertFalse(version_is_empty(kept))
		self.assertEqual(data["changed"][1], ["email", None, "anything"])  # input not mutated

	def test_empty_after_filter(self):
		data = {"changed": [["email", None, HER]], "row_changed": [["contacts", 1, "her-row", []]]}
		kept = filter_version_data(data, frozenset({"email"}), IDS, {"her-row"})
		self.assertTrue(version_is_empty(kept))
		self.assertTrue(version_is_empty({}))
		self.assertTrue(version_is_empty({"changed": [], "added": []}))

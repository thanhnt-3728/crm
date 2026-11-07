from frappe.tests import UnitTestCase

from crm.privacy.rules import (
	DEAL_FIELD_SOURCES,
	deal_fields_to_blank,
	replace_addresses,
	scrub_version_data,
)

EMAILS = {"marisol@sierrafoothills.example"}
PHONES = {"+15305550142"}
HER = {
	"first_name": {"marisol"},
	"last_name": {"vega"},
	"lead_name": {"marisol vega"},
	"full_name": {"marisol vega"},
}


class TestRulesStruct(UnitTestCase):
	def test_deal_fields_only_where_hers(self):
		deal = {
			"email": "Marisol@SierraFoothills.example",
			"mobile_no": "530 555 0142",
			"phone": "530-555-0100",
			"first_name": "Marisol",
			"last_name": "Okafor",
			"lead_name": "Marisol Vega",
		}
		self.assertEqual(
			sorted(deal_fields_to_blank(deal, HER, EMAILS, PHONES)),
			["email", "first_name", "lead_name", "mobile_no"],
		)

	def test_deal_of_someone_else_untouched(self):
		deal = {"email": "dana@x.example", "first_name": "Dana", "mobile_no": ""}
		self.assertEqual(deal_fields_to_blank(deal, HER, EMAILS, PHONES), [])

	def test_deal_name_match_is_stripped_and_casefolded(self):
		deal = {"last_name": "  VEGA ", "lead_name": None}
		self.assertEqual(deal_fields_to_blank(deal, HER, EMAILS, PHONES), ["last_name"])

	def test_deal_field_sources_pinned(self):
		self.assertEqual(DEAL_FIELD_SOURCES["lead_name"], ("lead_name", "full_name"))
		self.assertEqual(DEAL_FIELD_SOURCES["job_title"], ("job_title", "designation"))
		for key in ("first_name", "last_name", "salutation", "gender", "linkedin", "twitter", "facebook"):
			self.assertEqual(DEAL_FIELD_SOURCES[key], (key,))

	def test_deal_job_title_matches_designation(self):
		her = {"designation": {"vp sales"}}
		deal = {"job_title": "VP Sales"}
		self.assertEqual(deal_fields_to_blank(deal, her, EMAILS, PHONES), ["job_title"])

	def test_replace_addresses(self):
		out = replace_addresses(
			'"Marisol Vega" <Marisol@SierraFoothills.example>, tyler@northpine.example', EMAILS, "P"
		)
		self.assertEqual(out, "P, tyler@northpine.example")

	def test_replace_addresses_empty_and_multiple(self):
		self.assertEqual(replace_addresses(None, EMAILS, "P"), "")
		self.assertEqual(replace_addresses("", EMAILS, "P"), "")
		emails = EMAILS | {"m.vega@home.example"}
		out = replace_addresses("Marisol <marisol@sierrafoothills.example>, m.vega@home.example", emails, "P")
		self.assertEqual(out, "P, P")

	def test_replace_addresses_keeps_other_display_names(self):
		out = replace_addresses("Tyler Reed <tyler@northpine.example>", EMAILS, "P")
		self.assertEqual(out, "Tyler Reed <tyler@northpine.example>")

	def test_scrub_version_changed_rows(self):
		data = {
			"changed": [["email", "marisol@sierrafoothills.example", ""], ["status", "New", "Contacted"]],
			"added": [["email_ids", {"email_id": "marisol@sierrafoothills.example", "is_primary": 1}]],
			"row_changed": [["phone_nos", 1, "r1", [["phone", "5305550142", "+15305550142"]]]],
		}
		out = scrub_version_data(data, lambda f, v: f in {"email", "email_id", "phone"}, "P")
		self.assertEqual(out["changed"], [["email", "P", "P"], ["status", "New", "Contacted"]])
		self.assertEqual(out["added"][0][1], {"email_id": "P", "is_primary": 1})
		self.assertEqual(out["row_changed"][0][3], [["phone", "P", "P"]])
		self.assertEqual(data["changed"][0][1], "marisol@sierrafoothills.example")  # input not mutated
		self.assertEqual(data["added"][0][1]["email_id"], "marisol@sierrafoothills.example")

	def test_scrub_version_removed_passthrough_and_malformed(self):
		data = {
			"removed": [["email_ids", {"email_id": "x", "idx": 1}]],
			"comment": "kept",
			"changed": ["junk", ["a"], ["email", "x", "y"]],
			"added": [None, ["email_ids", "not-a-dict"]],
			"row_changed": [["t", 1], ["t", 1, "r", "bad"]],
		}
		out = scrub_version_data(data, lambda f, v: f in {"email_id", "email"}, "P")
		self.assertEqual(out["removed"][0][1], {"email_id": "P", "idx": 1})
		self.assertEqual(out["comment"], "kept")
		self.assertEqual(out["changed"][2], ["email", "P", "P"])

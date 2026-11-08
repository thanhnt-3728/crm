from frappe.tests import UnitTestCase

from crm.privacy.identifiers import normalize_identifier
from crm.privacy.rules import erased_content, erased_file, erased_person, scrub_identifiers


class TestRulesText(UnitTestCase):
	def test_placeholders(self):
		self.assertEqual(erased_person("PDR-0001"), "Erased person PDR-0001")
		self.assertEqual(erased_content("PDR-0001"), "Content erased PDR-0001")
		self.assertEqual(erased_file("PDR-0001"), "File erased PDR-0001")

	def test_scrub_email_and_phone_any_format(self):
		text = "Call Marisol at 530.555.0142 or mail MARISOL@sierrafoothills.example; office 530-555-0100"
		out = scrub_identifiers(text, {"marisol@sierrafoothills.example"}, {"+15305550142"}, "X")
		self.assertEqual(out, "Call Marisol at X or mail X; office 530-555-0100")

	def test_none_text(self):
		self.assertEqual(scrub_identifiers(None, {"a@b.example"}, set(), "X"), "")

	def test_email_whose_local_part_is_the_phone_is_replaced_whole(self):
		out = scrub_identifiers(
			"mail 5305550142@x.example now", {"5305550142@x.example"}, {"+15305550142"}, "X"
		)
		self.assertEqual(out, "mail X now")

	def test_email_only_matches_as_a_whole_address(self):
		text = "a xa@b.example and a@b.example.org"
		self.assertEqual(scrub_identifiers(text, {"a@b.example"}, set(), "X"), text)
		self.assertEqual(
			scrub_identifiers("Mail A@B.example, thanks", {"a@b.example"}, set(), "X"), "Mail X, thanks"
		)
		self.assertEqual(scrub_identifiers("<a@b.example>", {"a@b.example"}, set(), "X"), "<X>")

	def test_phone_without_valid_form_is_still_scrubbed(self):
		phone = normalize_identifier("Phone", "555 0100")
		self.assertEqual(scrub_identifiers("ext 555 0100 today", set(), {phone}, "X"), "ext X today")

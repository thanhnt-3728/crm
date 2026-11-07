from frappe.tests import UnitTestCase

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

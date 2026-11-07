from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.whatsapp import _resolve_reference
from crm.fcrm.doctype.crm_deal.test_crm_deal import create_test_contact, create_test_deal
from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource
from crm.privacy.blocking import IDENTIFIER_FIELDS, ErasedPersonError, identifier_fields
from crm.privacy.identifiers import add_do_not_contact

BLOCKED_EMAIL = "marisol@sierrafoothills.example"


def run_facebook_sync_with(data: dict, lead_id: str = "fb-blocking-1") -> None:
	"""Run `sync_single_lead` for a Meta lead whose mapped CRM fields are `data`."""
	lead = {"id": lead_id, "field_data": [{"name": key, "values": [value]} for key, value in data.items()]}
	source = FacebookSyncSource("test-token", "blocking-form")
	with patch.object(source, "get_form_questions_mapping", return_value={key: key for key in data}):
		source.sync_single_lead(lead)


class TestBlocking(IntegrationTestCase):
	def setUp(self):
		add_do_not_contact("Email", BLOCKED_EMAIL, "PDR-0001")
		add_do_not_contact("Phone", "5305550142", "PDR-0001")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_manual_lead_blocked_any_format(self):
		for kw in [{"email": "MARISOL@sierrafoothills.example"}, {"mobile_no": "(530) 555-0142"}]:
			with self.assertRaises(ErasedPersonError) as e:
				frappe.get_doc({"doctype": "CRM Lead", "first_name": "M", **kw}).insert()
			self.assertNotIn("530", str(e.exception))
			self.assertNotIn("marisol", str(e.exception).lower())

	def test_error_is_a_duplicate_entry_error(self):
		self.assertTrue(issubclass(ErasedPersonError, frappe.DuplicateEntryError))

	def test_contact_and_deal_row_blocked(self):
		with self.assertRaises(ErasedPersonError):
			create_test_contact(first_name="M", email=BLOCKED_EMAIL)
		c = create_test_contact(first_name="Front desk", phone="530-555-0100")
		frappe.db.set_value("Contact", c.name, "mobile_no", "5305550142")  # pre-existing shared value
		with self.assertRaises(ErasedPersonError):
			create_test_deal(contacts=[{"contact": c.name}])

	def test_deal_contact_row_alone_is_enough_to_block(self):
		c = create_test_contact(first_name="Front desk", phone="530-555-0100")
		frappe.db.set_value("Contact", c.name, "mobile_no", "5305550142")
		deal_spec = {"fields": {}, "tables": IDENTIFIER_FIELDS["CRM Deal"]["tables"]}
		with patch.dict(IDENTIFIER_FIELDS, {"CRM Deal": deal_spec}), self.assertRaises(ErasedPersonError):
			create_test_deal(contacts=[{"contact": c.name}])

	def test_contact_child_table_values_blocked(self):
		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Child"})
		contact.append("phone_nos", {"phone": "530 555 0142"})
		with self.assertRaises(ErasedPersonError):
			contact.insert(ignore_permissions=True)

	def test_adding_blocked_child_row_to_existing_contact(self):
		contact = create_test_contact(first_name="Other", email="other@x.example")
		contact.append("email_ids", {"email_id": BLOCKED_EMAIL})
		with self.assertRaises(ErasedPersonError):
			contact.save(ignore_permissions=True)

	def test_changing_existing_record_to_blocked_value(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Other", "email": "o@x.example"}).insert()
		lead.email = BLOCKED_EMAIL
		with self.assertRaises(ErasedPersonError):
			lead.save()

	def test_existing_record_saved_unchanged_not_blocked(self):
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Other", "mobile_no": "530-555-0100"}
		).insert()
		frappe.db.set_value("CRM Lead", lead.name, "phone", "5305550142")
		lead.reload()
		lead.job_title = "CEO"
		lead.save()

	def test_existing_contact_with_blocked_row_saved_unchanged(self):
		contact = create_test_contact(first_name="Shared", email="shared@x.example")
		frappe.db.set_value("Contact Phone", {"parent": contact.name}, "phone", "5305550142")
		contact.reload()
		contact.job_title = "CEO"
		contact.save(ignore_permissions=True)

	def test_deal_with_stale_contact_row_saves_when_contact_gained_blocked_number(self):
		c = create_test_contact(first_name="Stale", phone="530-555-0100")
		deal = create_test_deal(contacts=[{"contact": c.name}])
		# the contact later gains a number that belongs to an erased person; the deal's row is not refreshed
		frappe.db.set_value("Contact", c.name, "mobile_no", "5305550142")
		deal.reload()
		deal.deal_value = 5
		deal.save()

	def test_new_deal_row_for_contact_holding_blocked_value_blocks(self):
		keep = create_test_contact(first_name="Keep", phone="530-555-0100")
		deal = create_test_deal(contacts=[{"contact": keep.name}])
		other = create_test_contact(first_name="Other", phone="530-555-0101")
		frappe.db.set_value("Contact", other.name, "mobile_no", "5305550142")
		deal.reload()
		deal.append("contacts", {"contact": other.name})
		with self.assertRaises(ErasedPersonError):
			deal.save()

	def test_deal_row_pointing_at_another_contact_blocks(self):
		keep = create_test_contact(first_name="Keep", phone="530-555-0100")
		deal = create_test_deal(contacts=[{"contact": keep.name}])
		other = create_test_contact(first_name="Other", phone="530-555-0101")
		frappe.db.set_value("Contact", other.name, "mobile_no", "5305550142")
		deal.reload()
		deal.contacts[0].contact = other.name
		with self.assertRaises(ErasedPersonError):
			deal.save()

	def test_blocked_contact_save_leaves_linked_deal_untouched(self):
		c = create_test_contact(first_name="Primary", email="primary@x.example")
		deal = create_test_deal(contacts=[{"contact": c.name, "is_primary": 1}])
		versions = {"ref_doctype": "CRM Deal", "docname": deal.name}
		before_versions = frappe.db.count("Version", versions)
		before_mobile = frappe.db.get_value("CRM Deal", deal.name, "mobile_no")

		c.reload()
		c.append("phone_nos", {"phone": "5305550142", "is_primary_mobile_no": 1})
		with self.assertRaises(ErasedPersonError):
			c.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "mobile_no"), before_mobile)
		self.assertEqual(frappe.db.count("Version", versions), before_versions)

	def test_custom_personal_phone_field_blocks(self):
		meta = frappe.get_meta("CRM Lead")
		original = meta.get_field

		def get_field(name, *args, **kwargs):
			if name == "alt_phone":
				return frappe._dict(fieldname=name, fieldtype="Data", options="Phone")
			return original(name, *args, **kwargs)

		with (
			patch("crm.privacy.blocking.personal_fields", return_value={"CRM Lead": {"alt_phone", "gone"}}),
			patch.object(meta, "get_field", get_field),
		):
			self.assertEqual(identifier_fields("CRM Lead")["fields"]["alt_phone"], "Phone")
			self.assertNotIn("gone", identifier_fields("CRM Lead")["fields"])
			lead = frappe.new_doc("CRM Lead")
			lead.first_name = "Custom"
			lead.alt_phone = "(530) 555-0142"
			with self.assertRaises(ErasedPersonError):
				lead.insert()

	def test_custom_personal_email_field_is_an_email_identifier(self):
		meta = frappe.get_meta("CRM Lead")
		original = meta.get_field

		def get_field(name, *args, **kwargs):
			if name == "alt_email":
				return frappe._dict(fieldname=name, fieldtype="Data", options="Email")
			return original(name, *args, **kwargs)

		with (
			patch("crm.privacy.blocking.personal_fields", return_value={"CRM Lead": {"alt_email"}}),
			patch.object(meta, "get_field", get_field),
		):
			self.assertEqual(identifier_fields("CRM Lead")["fields"]["alt_email"], "Email")

	def test_unblocked_values_pass(self):
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Fine", "email": "fine@x.example"}
		).insert()
		self.assertTrue(lead.name)

	def test_facebook_sync_skips_without_failure_log(self):
		before = frappe.db.count("Failed Lead Sync Log")
		run_facebook_sync_with({"email": BLOCKED_EMAIL, "first_name": "M"})
		self.assertEqual(frappe.db.count("Failed Lead Sync Log"), before)
		self.assertFalse(frappe.db.exists("CRM Lead", {"first_name": "M"}))

	def test_facebook_sync_still_imports_unblocked_lead(self):
		run_facebook_sync_with({"email": "fine@x.example", "first_name": "Fine"}, lead_id="fb-blocking-2")
		self.assertTrue(frappe.db.exists("CRM Lead", {"facebook_lead_id": "fb-blocking-2"}))

	def _resolve_incoming(self, number: str):
		doc = MagicMock()
		doc.direction = "Incoming"
		doc.reference_doctype = None
		doc.reference_docname = None
		with (
			patch("crm.api.whatsapp.find_contact_lead_or_deal_from_number", return_value=(None, None)),
			patch("crm.api.whatsapp._lead_append_action", return_value=MagicMock()),
			patch("crm.api.whatsapp._create_lead", return_value="LEAD-NEW") as create,
		):
			_resolve_reference(doc, number)
		return doc, create

	def test_whatsapp_blocked_number_creates_no_lead(self):
		doc, create = self._resolve_incoming("+1 (530) 555-0142")
		create.assert_not_called()
		self.assertIsNone(doc.reference_doctype)
		self.assertIsNone(doc.reference_docname)

	def test_whatsapp_unblocked_number_still_creates_lead(self):
		doc, create = self._resolve_incoming("+1 530 555 0199")
		create.assert_called_once()
		self.assertEqual(doc.reference_docname, "LEAD-NEW")

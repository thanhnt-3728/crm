# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""CRM Privacy Settings: validation of the personal-field list and the idempotent install."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import NEVER_PERSONAL_FIELDS
from crm.privacy.install import DEFAULT_PERSONAL_FIELDS, setup
from crm.privacy.tests.make_test_user import make_user

SETTINGS = "CRM Privacy Settings"


def _rows(doc=None):
	doc = doc or frappe.get_doc(SETTINGS)
	return [(r.document_type, r.fieldname) for r in doc.personal_fields]


class PrivacySettingsTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		self.doc = frappe.get_doc(SETTINGS)

	def tearDown(self):
		frappe.db.rollback()

	def assert_row_rejected(self, document_type, fieldname):
		doc = frappe.get_doc(SETTINGS)
		doc.append("personal_fields", {"document_type": document_type, "fieldname": fieldname})
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestPersonalFieldValidation(PrivacySettingsTestCase):
	def test_unknown_fieldname_is_rejected(self):
		self.doc.append("personal_fields", {"document_type": "CRM Lead", "fieldname": "no_such_field"})
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.doc.save()
		self.assertIn("no_such_field", str(ctx.exception))

	def test_duplicate_rows_are_rejected(self):
		first = self.doc.personal_fields[0]
		self.assert_row_rejected(first.document_type, first.fieldname)

	def test_same_fieldname_on_another_doctype_is_not_a_duplicate(self):
		self.assertIn(("CRM Lead", "email"), _rows(self.doc))
		self.assertIn(("CRM Deal", "email"), _rows(self.doc))
		self.doc.save()

	@staticmethod
	def _drop_custom_field(name):
		# Custom Field DDL commits, so the rollback in tearDown cannot undo it: delete and commit
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name)
			frappe.db.commit()  # nosemgrep

	def test_custom_field_on_a_listed_doctype_is_accepted(self):
		name = "CRM Lead-personal_mobile_test"
		self.addCleanup(self._drop_custom_field, name)
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "CRM Lead",
				"fieldname": "personal_mobile_test",
				"fieldtype": "Data",
				"label": "Personal Mobile Test",
			}
		).insert()
		self.doc.append("personal_fields", {"document_type": "CRM Lead", "fieldname": "personal_mobile_test"})
		self.doc.save()
		self.assertIn(("CRM Lead", "personal_mobile_test"), _rows())

	def test_valid_row_saves(self):
		self.doc.append("personal_fields", {"document_type": "CRM Lead", "fieldname": "website"})
		self.doc.save()
		self.assertIn(("CRM Lead", "website"), _rows())

	def test_layout_and_table_fields_are_rejected(self):
		fields = frappe.get_meta("CRM Lead").fields
		layout = next(f.fieldname for f in fields if f.fieldtype == "Section Break")
		table = next(f.fieldname for f in fields if f.fieldtype == "Table")
		for fieldname in (layout, table):
			with self.subTest(fieldname=fieldname):
				self.assert_row_rejected("CRM Lead", fieldname)

	def test_report_critical_fields_are_rejected(self):
		cases = [
			("CRM Lead", "status"),
			("CRM Lead", "source"),
			("CRM Lead", "territory"),
			("CRM Lead", "lead_owner"),
			("CRM Lead", "annual_revenue"),
			("CRM Lead", "converted"),
			("CRM Deal", "deal_owner"),
			("CRM Deal", "organization"),
			("CRM Deal", "deal_value"),
			("CRM Deal", "expected_deal_value"),
			("CRM Deal", "probability"),
			("CRM Deal", "lead"),
			("CRM Deal", "closed_date"),
		]
		for document_type, fieldname in cases:
			with self.subTest(field=f"{document_type}.{fieldname}"):
				self.assertTrue(frappe.get_meta(document_type).has_field(fieldname))
				self.assert_row_rejected(document_type, fieldname)

	def test_standard_columns_are_rejected(self):
		for fieldname in ("name", "owner", "creation", "modified"):
			with self.subTest(fieldname=fieldname):
				self.assert_row_rejected("CRM Lead", fieldname)

	def test_no_default_personal_field_is_on_the_denylist(self):
		for document_type, fields in DEFAULT_PERSONAL_FIELDS.items():
			self.assertFalse(set(fields) & NEVER_PERSONAL_FIELDS, document_type)

	def test_head_of_compliance_must_be_an_enabled_user(self):
		off = make_user("head.off@example.com", enabled=0)
		on = make_user("head.on@example.com")
		for user, expected_ok in ((off, False), (on, True), (None, True)):
			doc = frappe.get_doc(SETTINGS)  # fresh: a doc that failed to save keeps its new timestamp
			doc.head_of_compliance = user
			if expected_ok:
				doc.save()
			else:
				with self.assertRaises(frappe.ValidationError):
					doc.save()


class TestSetupIdempotency(PrivacySettingsTestCase):
	def test_defaults_are_filled_with_every_listed_field_that_exists(self):
		rows = set(_rows())
		for doctype, fields in DEFAULT_PERSONAL_FIELDS.items():
			meta = frappe.get_meta(doctype)
			for fieldname in fields:
				if meta.has_field(fieldname):
					self.assertIn((doctype, fieldname), rows)
		for expected in [
			("CRM Lead", "first_name"),
			("CRM Lead", "mobile_no"),
			("CRM Deal", "lead_name"),
			("Contact", "email_id"),
			("Contact Email", "email_id"),
			("Contact Phone", "phone"),
			("CRM Contacts", "full_name"),
			("Address", "address_line1"),
		]:
			self.assertIn(expected, rows)

	def test_running_setup_twice_changes_nothing(self):
		before = _rows()
		modified = frappe.db.get_single_value(SETTINGS, "modified")
		setup()
		self.assertEqual(_rows(), before)
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "modified"), modified)

	def test_existing_rows_are_kept_and_not_refilled(self):
		frappe.db.delete("CRM Personal Field", {"parent": SETTINGS})
		doc = frappe.get_doc(SETTINGS)
		doc.append("personal_fields", {"document_type": "CRM Lead", "fieldname": "website"})
		doc.save()
		setup()
		self.assertEqual(_rows(), [("CRM Lead", "website")])

	def test_fieldnames_missing_from_meta_are_skipped_not_fatal(self):
		frappe.db.delete("CRM Personal Field", {"parent": SETTINGS})
		with patch.dict(
			"crm.privacy.install.DEFAULT_PERSONAL_FIELDS",
			{"CRM Lead": ["first_name", "not_in_this_version"]},
			clear=True,
		):
			setup()
		self.assertEqual(_rows(), [("CRM Lead", "first_name")])

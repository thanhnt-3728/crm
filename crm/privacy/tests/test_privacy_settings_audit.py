# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Saving the personal-fields list leaves an audit Comment that names who added and removed which rows."""

import frappe

from crm.privacy.tests.privacy_settings_case import SETTINGS, PrivacySettingsCase


class TestPrivacySettingsAudit(PrivacySettingsCase):
	def audit(self) -> list[str]:
		return frappe.get_all(
			"Comment",
			{"reference_doctype": SETTINGS, "reference_name": SETTINGS, "comment_type": "Info"},
			pluck="content",
			order_by="creation asc",
		)

	def test_adding_and_removing_rows_leaves_an_audit_comment(self):
		before = len(self.audit())
		rows = [
			r for r in self.rows_payload() if (r["document_type"], r["fieldname"]) != ("CRM Lead", "gender")
		]
		rows.append({"document_type": "CRM Lead", "fieldname": "website"})
		self.save(personal_fields=rows)
		(comment,) = self.audit()[before:]
		self.assertIn(self.admin, comment)
		self.assertIn("added", comment)
		self.assertIn("CRM Lead.website", comment)
		self.assertIn("removed", comment)
		self.assertIn("CRM Lead.gender", comment)
		self.assertNotIn("CRM Lead.email", comment)  # unchanged rows are not listed

	def test_a_save_that_changes_no_row_writes_no_comment(self):
		before = len(self.audit())
		self.save(contract_retention_months=12)
		self.assertEqual(len(self.audit()), before)

	def test_a_refused_save_writes_no_comment(self):
		before = len(self.audit())
		bad = {"document_type": "CRM Deal", "fieldname": "status"}
		with self.assertRaises(frappe.ValidationError):
			self.save(personal_fields=self.rows_payload(bad)[1:])
		self.assertEqual(len(self.audit()), before)

	def test_removing_only_names_the_rows_removed(self):
		before = len(self.audit())
		rows = [
			r for r in self.rows_payload() if (r["document_type"], r["fieldname"]) != ("Contact", "email_id")
		]
		self.save(personal_fields=rows)
		(comment,) = self.audit()[before:]
		self.assertIn("Contact.email_id", comment)
		self.assertNotIn("added", comment)

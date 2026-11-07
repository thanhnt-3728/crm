# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The privacy settings page's endpoints: System Manager only, validated at the boundary, secret never sent."""

from unittest.mock import patch

import frappe

from crm.api.erasure_settings import (
	get_personal_field_choices,
	get_privacy_settings,
	save_privacy_settings,
)
from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import NEVER_PERSONAL_FIELDS, get_dnc_secret
from crm.privacy.tests.make_test_user import as_user, make_user
from crm.privacy.tests.privacy_settings_case import PrivacySettingsCase


class TestPrivacySettingsApi(PrivacySettingsCase):
	def test_get_returns_the_settings_the_page_shows(self):
		data = as_user(self.admin, get_privacy_settings)
		self.assertIn("head_of_compliance", data)
		self.assertIn("contract_retention_months", data)
		self.assertIn(
			("CRM Lead", "email"), [(r["document_type"], r["fieldname"]) for r in data["personal_fields"]]
		)
		self.assertIn(data["secret_available"], (True, False))
		self.assertIsInstance(data["members"], list)

	def test_get_lists_the_document_types_a_row_may_use(self):
		types = as_user(self.admin, get_privacy_settings)["document_types"]
		self.assertEqual(types[0], "CRM Lead")
		self.assertIn("Address", types)

	def test_get_never_sends_the_secret_or_its_mask(self):
		data = as_user(self.admin, get_privacy_settings)
		self.assertNotIn("dnc_hash_secret", data)
		self.assertNotIn("*" * 64, frappe.as_json(data))

	def test_get_reports_a_missing_secret(self):
		with patch("crm.api.erasure_settings.secret_available", return_value=False):
			self.assertFalse(as_user(self.admin, get_privacy_settings)["secret_available"])

	def test_get_lists_compliance_members(self):
		dana = make_user("pdr.settings.dana@example.com", roles=["Compliance"])
		members = as_user(self.admin, get_privacy_settings)["members"]
		self.assertIn(dana, [m["user"] for m in members])

	def test_get_is_for_a_system_manager_only(self):
		for role in ("Sales Manager", "Sales User", "Compliance"):
			user = make_user(f"pdr.settings.{role.split()[-1].lower()}@example.com", roles=[role])
			with self.assertRaises(frappe.PermissionError):
				as_user(user, get_privacy_settings)

	# --- save

	def test_save_stores_head_retention_and_rows(self):
		extra = {"document_type": "CRM Lead", "fieldname": "website"}
		self.save(
			head_of_compliance=self.head,
			contract_retention_months=36,
			personal_fields=self.rows_payload(extra),
		)
		data = as_user(self.admin, get_privacy_settings)
		self.assertEqual(data["head_of_compliance"], self.head)
		self.assertEqual(data["contract_retention_months"], 36)
		self.assertIn(
			("CRM Lead", "website"), [(r["document_type"], r["fieldname"]) for r in data["personal_fields"]]
		)

	def test_save_can_remove_a_row_and_clear_the_head(self):
		self.save(head_of_compliance=self.head)
		rows = [
			r for r in self.rows_payload() if (r["document_type"], r["fieldname"]) != ("CRM Lead", "gender")
		]
		self.save(head_of_compliance=None, personal_fields=rows)
		data = as_user(self.admin, get_privacy_settings)
		self.assertFalse(data["head_of_compliance"])
		self.assertNotIn(
			("CRM Lead", "gender"), [(r["document_type"], r["fieldname"]) for r in data["personal_fields"]]
		)

	def test_save_refuses_a_field_that_reports_group_by(self):
		bad = {"document_type": "CRM Deal", "fieldname": "status"}
		with self.assertRaises(frappe.ValidationError):
			self.save(personal_fields=self.rows_payload(bad))
		self.assertIn("status", NEVER_PERSONAL_FIELDS)

	def test_save_refuses_an_unknown_field_and_a_duplicate(self):
		for bad in (
			{"document_type": "CRM Lead", "fieldname": "no_such_field"},
			{"document_type": "CRM Lead", "fieldname": "email"},
		):
			with self.assertRaises(frappe.ValidationError):
				self.save(personal_fields=self.rows_payload(bad))

	def test_save_refuses_malformed_rows(self):
		for rows in (["CRM Lead.email"], [{"document_type": "CRM Lead"}], [{"fieldname": "email"}]):
			with self.assertRaises(frappe.ValidationError):
				self.save(personal_fields=rows)
		with self.assertRaises(frappe.exceptions.FrappeTypeError):  # the type check stops a bare string first
			self.save(personal_fields="email")

	def test_save_refuses_a_negative_retention_and_a_disabled_head(self):
		with self.assertRaises(frappe.ValidationError):
			self.save(contract_retention_months=-1)
		off = make_user("pdr.settings.off@example.com", roles=["Sales Manager"], enabled=0)
		with self.assertRaises(frappe.ValidationError):
			self.save(head_of_compliance=off)

	def test_save_does_not_touch_the_secret(self):
		before = get_dnc_secret()
		self.save()
		self.assertEqual(get_dnc_secret(), before)

	def test_save_is_for_a_system_manager_only(self):
		for caller in (self.head, make_user("pdr.settings.dana2@example.com", roles=["Compliance"])):
			with self.assertRaises(frappe.PermissionError):
				as_user(caller, save_privacy_settings, None, 12, self.rows_payload())
		self.assertEqual(as_user(self.admin, get_privacy_settings)["contract_retention_months"], 0)

	# --- field choices

	def test_choices_list_value_fields_of_the_doctype(self):
		choices = as_user(self.admin, get_personal_field_choices, "CRM Lead")
		names = {c["fieldname"] for c in choices}
		self.assertIn("email", names)
		self.assertTrue(all({"fieldname", "label", "fieldtype"} <= set(c) for c in choices))

	def test_choices_leave_out_layout_table_and_report_fields(self):
		names = {c["fieldname"] for c in as_user(self.admin, get_personal_field_choices, "CRM Deal")}
		self.assertNotIn("contacts", names)  # a table
		self.assertFalse(names & NEVER_PERSONAL_FIELDS)
		fieldtypes = {c["fieldtype"] for c in as_user(self.admin, get_personal_field_choices, "CRM Deal")}
		self.assertFalse(fieldtypes & {"Section Break", "Column Break", "Tab Break", "Table"})

	def test_choices_refuse_a_doctype_the_list_does_not_allow(self):
		with self.assertRaises(frappe.ValidationError):
			as_user(self.admin, get_personal_field_choices, "User")

	def test_choices_are_for_a_system_manager_only(self):
		with self.assertRaises(frappe.PermissionError):
			as_user(self.head, get_personal_field_choices, "CRM Lead")

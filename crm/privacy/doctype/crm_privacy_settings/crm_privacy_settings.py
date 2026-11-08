# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields
from frappe.model.document import Document

from crm.privacy.rules import FORBIDDEN_PERSONAL_FIELDS


class CRMPrivacySettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.privacy.doctype.crm_personal_field.crm_personal_field import CRMPersonalField

		contract_retention_months: DF.Int
		head_of_compliance: DF.Link | None
		personal_fields: DF.Table[CRMPersonalField]
	# end: auto-generated types

	def validate(self):
		self.validate_personal_fields()

	def validate_personal_fields(self):
		"""Refuse an empty list, unknown fields, tables and layout fields, and report fields.

		Name, email and phone fields are erased whether listed or not
		(`crm.privacy.identifiers.personal_fields`).
		"""
		if not self.personal_fields:
			frappe.throw(_("List at least one personal field"), frappe.ValidationError)
		for row in self.personal_fields:
			row.fieldname = (row.fieldname or "").strip()
			label = f"{row.document_type} {row.fieldname}"
			if row.fieldname in FORBIDDEN_PERSONAL_FIELDS:
				frappe.throw(
					_("{0} is used by reports and cannot be listed as a personal field").format(label),
					frappe.ValidationError,
				)
			df = frappe.get_meta(row.document_type).get_field(row.fieldname)
			if not df:
				frappe.throw(_("{0} is not a field").format(label), frappe.ValidationError)
			if df.fieldtype in no_value_fields or df.fieldtype in table_fields:
				frappe.throw(
					_("{0} is a table or layout field, not a value that can be erased").format(label),
					frappe.ValidationError,
				)

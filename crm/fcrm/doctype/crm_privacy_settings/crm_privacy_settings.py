# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# The fields that identify the person on each record type. Admins can add personal fields
# but not take these off: without them erasure would leave the person's name, email and
# phone in place and report success.
CORE_PERSONAL_FIELDS = {
	"CRM Lead": ("email", "mobile_no", "phone", "first_name", "last_name", "lead_name"),
	"CRM Deal": ("email", "mobile_no", "phone", "first_name", "last_name", "lead_name"),
	"Contact": ("email_id", "mobile_no", "phone", "first_name", "last_name", "full_name"),
	"CRM Contacts": ("email", "mobile_no", "phone", "full_name"),
}


def missing_core_fields(rows) -> list[tuple[str, str]]:
	"""(document type, fieldname) of the core personal fields `rows` do not list."""
	listed = {(row.document_type, (row.fieldname or "").strip()) for row in rows}
	return [
		(doctype, fieldname)
		for doctype, fieldnames in CORE_PERSONAL_FIELDS.items()
		for fieldname in fieldnames
		if (doctype, fieldname) not in listed
	]


class CRMPrivacySettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.fcrm.doctype.crm_personal_field.crm_personal_field import CRMPersonalField

		contract_retention_months: DF.Int
		hash_secret: DF.Password | None
		head_of_compliance: DF.Link | None
		personal_fields: DF.Table[CRMPersonalField]
	# end: auto-generated types

	def validate(self):
		for row in self.personal_fields:
			row.validate_fieldname()
		self.validate_core_fields()

	def validate_core_fields(self):
		missing = missing_core_fields(self.personal_fields)
		if missing:
			frappe.throw(
				_("These personal fields identify the person and can't be removed: {0}").format(
					", ".join(f"{doctype}.{fieldname}" for doctype, fieldname in missing)
				)
			)

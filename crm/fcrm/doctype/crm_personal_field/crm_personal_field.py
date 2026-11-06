# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMPersonalField(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		document_type: DF.Literal["CRM Lead", "CRM Deal", "Contact", "CRM Contacts", "Address"]
		fieldname: DF.Data
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	def validate_fieldname(self):
		"""The field must exist on its document type. A typo would otherwise be accepted and
		the real field silently skipped by erasure."""
		fieldname = (self.fieldname or "").strip()
		if not fieldname or not self.document_type:
			frappe.throw(_("Row {0}: choose a document type and a field.").format(self.idx))
		if not frappe.get_meta(self.document_type).has_field(fieldname):
			frappe.throw(
				_("Row {0}: {1} is not a field of {2}.").format(
					self.idx, frappe.bold(fieldname), self.document_type
				)
			)
		self.fieldname = fieldname

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMErasureMatch(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		confirmed: DF.Check
		is_source: DF.Check
		label: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		reason: DF.SmallText | None
		reference_doctype: DF.Literal["CRM Lead", "CRM Deal", "Contact"]
		reference_name: DF.DynamicLink
		relation: DF.Literal["Direct", "Linked", "Hold deal", "Removed from open deal"]
	# end: auto-generated types

	pass

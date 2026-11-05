# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class CRMRetainedContract(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		contract_reference: DF.Data
		delete_after: DF.Date | None
		person_name: DF.Data | None
		request: DF.Data | None
	# end: auto-generated types

	pass

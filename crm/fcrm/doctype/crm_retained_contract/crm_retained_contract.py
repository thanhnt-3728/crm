# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMRetainedContract(Document):
	"""Her name and a contract reference, kept after an erasure for as long as counsel sets (design 5.11).
	Written only by the erasure job; deleted by the daily purge on `delete_after`. Compliance can read it."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		contract_reference: DF.Data
		delete_after: DF.Date
		person_name: DF.Data
		request: DF.Data | None
	# end: auto-generated types

	pass

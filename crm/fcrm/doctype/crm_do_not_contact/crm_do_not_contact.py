# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMDoNotContact(Document):
	"""One erased email or phone, as a keyed hash (design 5.9). It has no link to the request: it outlives
	close and purge. Only server code writes it (`crm.privacy.do_not_contact.add_entries`); the doctype
	gives Compliance read access and nobody write access."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		created_on: DF.Date | None
		identifier_hash: DF.Data
		kind: DF.Literal["Email", "Phone"]
	# end: auto-generated types

	pass

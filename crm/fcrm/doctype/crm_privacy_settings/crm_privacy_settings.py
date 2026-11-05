# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


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

	pass

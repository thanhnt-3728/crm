# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password, set_encrypted_password

SETTINGS = "CRM Privacy Settings"
SECRET_FIELD = "dnc_hash_secret"
SECRET_MASK = "*" * 64  # what the document shows once a secret exists; the key lives only in __Auth
DNC_DOCTYPE = "CRM Do Not Contact"

# Fields that dashboards and reports group by or sum (design 3), plus standard columns and the
# links that hold the records together. Erasure blanks personal fields in place, so listing one of
# these would move the numbers or break a link. Matched by fieldname on any listed doctype.
NEVER_PERSONAL_FIELDS = frozenset(
	{
		# standard columns
		"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "naming_series",
		# status, source, territory, owners, organization
		"status", "source", "territory", "lead_owner", "deal_owner", "organization", "organization_name",
		"industry", "no_of_employees", "annual_revenue", "lost_reason",
		# values and dates
		"deal_value", "expected_deal_value", "net_total", "total", "probability", "currency",
		"exchange_rate", "expected_closure_date", "closed_date", "converted",
		# links between records, SLA and communication state
		"lead", "contact", "sla", "sla_status", "sla_creation", "response_by", "first_response_time",
		"first_responded_on", "communication_status", "lead_score", "lead_temperature",
	}
)  # fmt: skip


class DncSecretUnavailableError(frappe.ValidationError):
	"""The do-not-contact hash secret is gone while hashed entries exist. Regenerating it would
	orphan every block, so callers must stop until it is restored from a backup."""


def _dnc_entries_exist() -> bool:
	# The doctype ships in a later phase, so its table may not exist yet.
	return bool(frappe.db.table_exists(DNC_DOCTYPE) and frappe.db.count(DNC_DOCTYPE))


def _stored_secret() -> str | None:
	return get_decrypted_password(SETTINGS, SETTINGS, SECRET_FIELD, raise_exception=False)


def get_dnc_secret() -> str:
	"""The HMAC key for do-not-contact hashes (design 5.9), created on first use.

	Generated once with `secrets.token_hex(32)` under a row lock, so two workers cannot each create
	one. If it is missing while entries exist it is NOT regenerated: raises DncSecretUnavailableError.
	How each caller reacts (fail closed or soft) is that caller's decision."""
	if secret := _stored_secret():
		return secret

	# Lock a row every worker shares, then look again: another worker may have created it meanwhile.
	frappe.db.get_value("DocType", SETTINGS, "name", for_update=True)
	if secret := _stored_secret():
		return secret

	if _dnc_entries_exist():
		raise DncSecretUnavailableError(
			_(
				"The do-not-contact hash secret is missing, so blocked contacts cannot be checked. "
				"It must be restored from a backup (the __Auth row for CRM Privacy Settings together "
				"with the site's encryption_key). Contact your system administrator."
			)
		)

	secret = secrets.token_hex(32)
	set_encrypted_password(SETTINGS, SETTINGS, secret, SECRET_FIELD)
	frappe.db.set_single_value(SETTINGS, SECRET_FIELD, SECRET_MASK, update_modified=False)
	return secret


class CRMPrivacySettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.fcrm.doctype.crm_personal_field.crm_personal_field import CRMPersonalField

		contract_retention_months: DF.Int
		dnc_hash_secret: DF.Password | None
		head_of_compliance: DF.Link | None
		personal_fields: DF.Table[CRMPersonalField]
	# end: auto-generated types

	def before_validate(self):
		# Frappe deletes a Password value from __Auth when the field is empty on save, and the key
		# is never held on the document. Keep it out of document saves entirely, and show a mask
		# whatever a form or API payload sent.
		self.flags.ignore_save_passwords = [SECRET_FIELD]
		self.dnc_hash_secret = SECRET_MASK if _stored_secret() else None

	def validate(self):
		self.validate_head_of_compliance()
		self.validate_personal_fields()

	def validate_head_of_compliance(self):
		if self.head_of_compliance and not frappe.db.get_value("User", self.head_of_compliance, "enabled"):
			frappe.throw(_("Head of Compliance must be an enabled user"))

	def validate_personal_fields(self):
		seen = set()
		for row in self.personal_fields:
			row.fieldname = (row.fieldname or "").strip()
			key = (row.document_type, row.fieldname)
			if key in seen:
				frappe.throw(
					_("Row #{0}: {1} - {2} is listed more than once").format(
						row.idx, _(row.document_type), row.fieldname
					)
				)
			seen.add(key)

			if row.fieldname in NEVER_PERSONAL_FIELDS:
				frappe.throw(
					_("Row #{0}: {1} is used in reports and cannot be erased").format(row.idx, row.fieldname)
				)
			# get_meta merges custom fields, so a custom field added by an admin passes
			field = frappe.get_meta(row.document_type).get_field(row.fieldname)
			if not field:
				frappe.throw(
					_("Row #{0}: {1} has no field named {2}").format(
						row.idx, _(row.document_type), row.fieldname
					)
				)
			if field.fieldtype in no_value_fields or field.fieldtype in table_fields:
				frappe.throw(
					_("Row #{0}: {1} is a layout or table field and holds no personal data").format(
						row.idx, row.fieldname
					)
				)

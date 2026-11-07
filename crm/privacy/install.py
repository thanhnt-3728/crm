# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Privacy compliance setup: Compliance role, personal-field defaults, DNC secret.

Called from `crm.install.after_install` and the `add_privacy_compliance_setup` patch. Idempotent:
running it again changes nothing.
"""

import frappe

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import (
	SETTINGS,
	DncSecretUnavailableError,
	get_dnc_secret,
)
from crm.privacy.outcome_template import install_outcome_template
from crm.privacy.roles import COMPLIANCE_ROLE

DEFAULT_PERSONAL_FIELDS = {
	"CRM Lead": [
		"salutation", "first_name", "middle_name", "last_name", "lead_name", "email", "mobile_no",
		"phone", "job_title", "image", "gender", "linkedin", "twitter", "facebook",
	],
	"CRM Deal": [
		"salutation", "first_name", "last_name", "lead_name", "email", "mobile_no", "phone",
		"job_title", "gender", "linkedin", "twitter", "facebook",
	],
	"Contact": [
		"salutation", "first_name", "middle_name", "last_name", "full_name", "email_id", "mobile_no",
		"phone", "designation", "image", "gender",
	],
	"Contact Email": ["email_id"],
	"Contact Phone": ["phone"],
	"CRM Contacts": ["full_name", "email", "mobile_no", "phone", "gender"],
	"Address": [
		"address_title", "address_line1", "address_line2", "city", "county", "state", "pincode",
		"email_id", "phone", "fax",
	],
}  # fmt: skip


def setup():
	create_compliance_role()
	add_default_personal_fields()
	create_dnc_secret()
	install_outcome_template()


def create_dnc_secret():
	"""Create the secret once. A site restored with another `encryption_key` has entries and no secret: a new
	one would orphan every block, so it is left alone (the block paths report it) and install carries on."""
	try:
		get_dnc_secret()
	except DncSecretUnavailableError:
		pass


def create_compliance_role():
	"""Desk access on, like Sales User and Sales Manager: without it a user holding only Compliance
	becomes a Website User and is locked out of the CRM. An existing role with it off is fixed."""
	if frappe.db.exists("Role", COMPLIANCE_ROLE):
		if not frappe.db.get_value("Role", COMPLIANCE_ROLE, "desk_access"):
			frappe.db.set_value("Role", COMPLIANCE_ROLE, "desk_access", 1)
		return
	frappe.get_doc({"doctype": "Role", "role_name": COMPLIANCE_ROLE, "desk_access": 1}).insert(
		ignore_permissions=True
	)


def add_default_personal_fields():
	"""Pre-fill the list only when it is empty, so an admin's edits are never undone. Fieldnames
	missing from this Frappe version's meta are skipped and logged, so validate never blocks install."""
	settings = frappe.get_doc(SETTINGS)
	if settings.personal_fields:
		return

	for document_type, fieldnames in DEFAULT_PERSONAL_FIELDS.items():
		meta = frappe.get_meta(document_type)
		for fieldname in fieldnames:
			if meta.has_field(fieldname):
				settings.append("personal_fields", {"document_type": document_type, "fieldname": fieldname})
			else:
				frappe.logger("crm").warning(
					f"CRM Privacy Settings: skipped default personal field {document_type}.{fieldname} (not in meta)"
				)
	settings.save(ignore_permissions=True)

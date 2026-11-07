"""Install/migrate hooks for the privacy (erasure request) module."""

import frappe

from crm.privacy.identifiers import ensure_secret
from crm.privacy.rules import DEFAULT_PERSONAL_FIELDS

COMPLIANCE_ROLE = "Compliance"


def after_migrate() -> None:
	ensure_compliance_role()
	ensure_secret()
	seed_personal_fields()


def ensure_compliance_role() -> None:
	if frappe.db.exists("Role", COMPLIANCE_ROLE):
		return
	frappe.get_doc({"doctype": "Role", "role_name": COMPLIANCE_ROLE, "desk_access": 1}).insert(
		ignore_permissions=True
	)


def seed_personal_fields() -> None:
	"""Fill the personal-fields table from the defaults, only while it is empty.

	Leaving a non-empty table alone means rows an admin removed stay removed.
	"""
	settings = frappe.get_single("CRM Privacy Settings")
	if settings.personal_fields:
		return
	for document_type, fieldnames in DEFAULT_PERSONAL_FIELDS.items():
		for fieldname in fieldnames:
			settings.append("personal_fields", {"document_type": document_type, "fieldname": fieldname})
	settings.save(ignore_permissions=True)

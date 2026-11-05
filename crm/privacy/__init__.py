import frappe


def settings():
	"""The CRM Privacy Settings single, cached."""
	return frappe.get_cached_doc("CRM Privacy Settings")


def personal_fields(doctype: str) -> set[str]:
	"""Fieldnames of `doctype` that hold personal data, per the privacy settings."""
	return {row.fieldname for row in settings().personal_fields if row.document_type == doctype}


def compliance_users() -> list[str]:
	"""Enabled users who hold the Compliance role."""
	holders = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": "Compliance"},
		pluck="parent",
		distinct=True,
	)
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")

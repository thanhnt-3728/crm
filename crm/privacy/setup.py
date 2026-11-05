import frappe

DEFAULT_PERSONAL_FIELDS = {
	"CRM Lead": [
		"salutation",
		"first_name",
		"middle_name",
		"last_name",
		"lead_name",
		"gender",
		"email",
		"mobile_no",
		"phone",
		"job_title",
		"image",
		"linkedin",
		"twitter",
		"facebook",
	],
	"CRM Deal": [
		"salutation",
		"first_name",
		"last_name",
		"lead_name",
		"gender",
		"email",
		"mobile_no",
		"phone",
		"job_title",
		"linkedin",
		"twitter",
		"facebook",
	],
	"Contact": [
		"salutation",
		"first_name",
		"middle_name",
		"last_name",
		"full_name",
		"gender",
		"email_id",
		"mobile_no",
		"phone",
		"designation",
		"image",
	],
	"CRM Contacts": ["full_name", "email", "mobile_no", "phone", "gender"],
	"Address": [
		"address_title",
		"address_line1",
		"address_line2",
		"city",
		"county",
		"state",
		"pincode",
		"email_id",
		"phone",
		"fax",
	],
}


def ensure_privacy_setup():
	"""Create the Compliance role and seed the privacy settings. Safe to run repeatedly."""
	if not frappe.db.exists("Role", "Compliance"):
		frappe.get_doc({"doctype": "Role", "role_name": "Compliance", "desk_access": 1}).insert(
			ignore_permissions=True
		)

	doc = frappe.get_doc("CRM Privacy Settings")
	changed = False

	if not doc.personal_fields:
		for document_type, fieldnames in DEFAULT_PERSONAL_FIELDS.items():
			for fieldname in fieldnames:
				doc.append("personal_fields", {"document_type": document_type, "fieldname": fieldname})
		changed = True

	if not doc.get_password("hash_secret", raise_exception=False):
		doc.hash_secret = frappe.generate_hash(length=64)
		changed = True

	if changed:
		doc.save(ignore_permissions=True)

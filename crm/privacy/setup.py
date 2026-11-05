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

OUTCOME_TEMPLATE_NAME = "Erasure outcome"
OUTCOME_TEMPLATE_SUBJECT = "Your request to erase your personal information"
# Compliance fills the [bracketed] parts before sending.
OUTCOME_TEMPLATE_BODY = """<p>Hello,</p>
<p>Thank you for your request to erase your personal information. This is our answer.</p>
<h4>What we erased</h4>
<p>We erased the following from our systems: [categories, for example contact details, lead and deal records, emails, calls, notes, files].</p>
<p>Erased at external providers as well: [yes/no + providers].</p>
<h4>What we kept and why</h4>
<p>[items and reasons, for example name and contract reference under the signed-contract exception, or a partial denial and its reason]</p>
<h4>What we keep to show we handled your request</h4>
<p>We keep a record of this request for 24 months: the date we received it, its type, how it arrived, the date we answered and the outcome. We also keep a scrambled form of your email address and phone number, so your details are not added to our systems again.</p>
<h4>A limitation you should know about</h4>
<p>Passing mentions of you inside records about other people, such as a note on a deal, are not searched for or erased.</p>
<p>[Compliance contact details]</p>"""


def ensure_outcome_template():
	"""Create the "Erasure outcome" email template. An existing one is left as the admin edited it."""
	if frappe.db.exists("Email Template", OUTCOME_TEMPLATE_NAME):
		return
	values = {
		"doctype": "Email Template",
		"name": OUTCOME_TEMPLATE_NAME,
		"subject": OUTCOME_TEMPLATE_SUBJECT,
		"response": OUTCOME_TEMPLATE_BODY,
	}
	# CRM adds an `enabled` flag to Email Template; templates are not offered while it is off.
	if frappe.get_meta("Email Template").has_field("enabled"):
		values["enabled"] = 1
	frappe.get_doc(values).insert(ignore_permissions=True)


def ensure_privacy_setup():
	"""Create the Compliance role, seed the privacy settings and the outcome email template.
	Safe to run repeatedly."""
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

	ensure_outcome_template()

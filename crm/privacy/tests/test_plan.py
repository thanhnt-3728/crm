import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_deal.crm_deal import remove_contact
from crm.permissions.test_org_hierarchy import make_user
from crm.privacy.api import get_erasure_preview
from crm.privacy.plan import plan_erasure, preview, unlisted_custom_fields
from crm.privacy.tests.factories import (
	make_call_log,
	make_communication,
	make_compliance_user,
	make_marisol,
	make_note,
	make_request,
)

EMAIL = "marisol@sierrafoothills.example"


def _comment(doctype: str, name: str) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": doctype,
				"reference_name": name,
				"content": "A comment",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _task(doctype: str, name: str) -> str:
	doc = frappe.get_doc(
		{"doctype": "CRM Task", "title": "Follow up", "reference_doctype": doctype, "reference_docname": name}
	)
	return str(doc.insert(ignore_permissions=True).name)


def _file(doctype: str, name: str, file_name: str = "a.txt", **fields) -> str:
	values = {
		"doctype": "File",
		"file_name": file_name,
		"file_url": f"/private/files/{file_name}",
		"is_private": 1,
		"attached_to_doctype": doctype,
		"attached_to_name": name,
		**fields,
	}
	doc = frappe.get_doc(values)
	# A plain insert would read the file from disk; these tests only need the row.
	doc.name = frappe.generate_hash(length=10)
	doc.set_user_and_timestamp()
	doc.db_insert()
	return doc.name


def _address(title: str, links: list[dict] | None = None) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_line1": "1 Main St",
				"city": "Auburn",
				"country": "United States",
				"links": links or [],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestPlan(IntegrationTestCase):
	def setUp(self):
		self.m = make_marisol()
		self.r = make_request(
			identifiers=[{"kind": "Email", "value": EMAIL}, {"kind": "Phone", "value": "5305550142"}],
			matches=[
				{"reference_doctype": d, "reference_name": n, "confirmed": 1}
				for d, n in [
					("CRM Lead", self.m.lead),
					("Contact", self.m.contact),
					("CRM Deal", self.m.won_deal),
					("CRM Deal", self.m.open_deal),
				]
			],
		)
		remove_contact(self.m.open_deal, self.m.contact)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_still_on_vs_removed(self):
		p = plan_erasure(self.r)
		self.assertEqual(p.deals_on, [self.m.won_deal])
		self.assertEqual(p.deals_removed, [self.m.open_deal])
		self.assertEqual(p.leads, [self.m.lead])
		self.assertEqual(p.contacts, [self.m.contact])
		self.assertEqual(p.emails, {EMAIL})
		self.assertEqual(p.phones, {"+15305550142"})

	def test_plan_accepts_a_request_name(self):
		self.assertEqual(plan_erasure(self.r.name).request, self.r.name)

	def test_deal_with_her_email_is_still_on_even_without_contact_link(self):
		frappe.db.set_value("CRM Deal", self.m.open_deal, "email", "MARISOL@sierrafoothills.example")
		p = plan_erasure(self.r)
		self.assertEqual(sorted(p.deals_on), sorted([self.m.open_deal, self.m.won_deal]))
		self.assertEqual(p.deals_removed, [])

	def test_excluded_identifier_is_left_out(self):
		self.r.identifiers[1].excluded = 1
		self.r.save()
		self.assertEqual(plan_erasure(self.r).phones, set())

	def test_her_values_from_leads_and_contacts(self):
		v = plan_erasure(self.r).her_values
		self.assertEqual(v["first_name"], {"marisol"})
		self.assertEqual(v["last_name"], {"vega"})
		self.assertEqual(v["lead_name"], {"marisol vega"})
		self.assertEqual(v["full_name"], {"marisol vega"})
		self.assertEqual(v["job_title"], {"office manager"})
		self.assertNotIn("middle_name", v)

	def test_email_by_address_anywhere_and_notes_on_removed_deal_kept(self):
		c = make_communication(
			sender="Marisol Vega <MARISOL@sierrafoothills.example>", reference=("CRM Deal", self.m.open_deal)
		)
		n = make_note(("CRM Deal", self.m.open_deal))
		p = plan_erasure(self.r)
		self.assertIn(c, p.communications)
		self.assertNotIn(n, p.notes)

	def test_email_in_recipients_cc_bcc(self):
		a = make_communication(sender="rep@example.com", recipients=f"Marisol Vega <{EMAIL}>, other@example.com")
		b = make_communication(sender="rep@example.com", cc=EMAIL)
		c = make_communication(sender="rep@example.com", bcc="x@example.com, MARISOL@sierrafoothills.EXAMPLE")
		p = plan_erasure(self.r)
		self.assertTrue({a, b, c} <= set(p.communications))

	def test_lookalike_addresses_are_not_confirmed(self):
		a = make_communication(sender="rep@example.com", recipients="marisol@sierrafoothills.example.org")
		b = make_communication(sender="rep@example.com", recipients="xmarisol@sierrafoothills.example")
		c = make_communication(
			sender="rep@example.com", recipients='"marisol@sierrafoothills.example" <other@example.com>'
		)
		d = make_communication(sender="m_risol@sierrafoothills.example")
		p = plan_erasure(self.r)
		self.assertFalse({a, b, c, d} & set(p.communications))

	def test_communication_on_her_records_or_timeline_link(self):
		a = make_communication(sender="rep@example.com", reference=("CRM Lead", self.m.lead))
		b = make_communication(sender="rep@example.com", reference=("CRM Deal", self.m.open_deal))
		linked = make_communication(sender="rep@example.com")
		doc = frappe.get_doc("Communication", linked)
		doc.append("timeline_links", {"link_doctype": "Contact", "link_name": self.m.contact})
		doc.save(ignore_permissions=True)
		p = plan_erasure(self.r)
		self.assertIn(a, p.communications)
		self.assertNotIn(b, p.communications)
		self.assertIn(linked, p.communications)

	def test_call_log_matched_by_formatted_number_and_recording_flag(self):
		cl = make_call_log(**{"from": "530.555.0142", "to": "+15550001111", "recording_url": "https://api.twilio.com/r/1"})
		p = plan_erasure(self.r)
		self.assertIn(cl, p.call_logs)
		self.assertTrue(p.has_recordings)

	def test_call_logs_by_record_and_link_and_no_recordings(self):
		other = make_call_log(**{"from": "+15550002222", "to": "+15550001111"})
		on_lead = make_call_log(
			**{"from": "+15550002222", "reference_doctype": "CRM Lead", "reference_docname": self.m.lead}
		)
		linked = make_call_log(
			**{"from": "+15550002222", "links": [{"link_doctype": "Contact", "link_name": self.m.contact}]}
		)
		p = plan_erasure(self.r)
		self.assertNotIn(other, p.call_logs)
		self.assertTrue({on_lead, linked} <= set(p.call_logs))
		self.assertFalse(p.has_recordings)

	def test_notes_tasks_comments_on_her_records_and_notes_from_call_logs(self):
		lead_note = make_note(("CRM Lead", self.m.lead))
		deal_note = make_note(("CRM Deal", self.m.won_deal))
		removed_note = make_note(("CRM Deal", self.m.open_deal))
		call_note = make_note(("CRM Deal", self.m.open_deal))
		make_call_log(**{"from": "+15305550142", "note": call_note})
		task = _task("Contact", self.m.contact)
		removed_task = _task("CRM Deal", self.m.open_deal)
		comment = _comment("CRM Lead", self.m.lead)
		removed_comment = _comment("CRM Deal", self.m.open_deal)
		p = plan_erasure(self.r)
		self.assertTrue({lead_note, deal_note, call_note} <= set(p.notes))
		self.assertNotIn(removed_note, p.notes)
		self.assertIn(task, p.tasks)
		self.assertNotIn(removed_task, p.tasks)
		self.assertIn(comment, p.comments)
		self.assertNotIn(removed_comment, p.comments)

	def test_addresses_linked_to_contact(self):
		linked = _address("Marisol home", [{"link_doctype": "Contact", "link_name": self.m.contact}])
		unrelated = _address("Other")
		via_field = _address("Field")
		frappe.db.set_value("Contact", self.m.contact, "address", via_field)
		p = plan_erasure(self.r)
		self.assertTrue({linked, via_field} <= set(p.addresses))
		self.assertNotIn(unrelated, p.addresses)

	def test_files_on_records_emails_and_images(self):
		on_lead = _file("CRM Lead", self.m.lead, "lead.txt")
		on_removed = _file("CRM Deal", self.m.open_deal, "removed.txt")
		comm = make_communication(sender=EMAIL)
		on_comm = _file("Communication", comm, "mail.txt")
		frappe.db.set_value("Contact", self.m.contact, "image", "/files/photo.png")
		photo = _file("User", "Administrator", "photo.png", file_url="/files/photo.png", is_private=0)
		p = plan_erasure(self.r)
		self.assertTrue({on_lead, on_comm, photo} <= set(p.files))
		self.assertNotIn(on_removed, p.files)

	def test_preview_flags_unlisted_custom_field(self):
		doc = frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "CRM Lead",
				"fieldname": "personal_mobile",
				"fieldtype": "Data",
				"label": "Personal mobile",
				"insert_after": "mobile_no",
			}
		)
		doc.name = "CRM Lead-personal_mobile"
		doc.set_user_and_timestamp()
		doc.db_insert()
		self.assertIn("personal_mobile", [f["fieldname"] for f in unlisted_custom_fields()])
		out = preview(plan_erasure(self.r))
		self.assertIn("personal_mobile", [f["fieldname"] for f in out["warnings"]["unlisted_custom_fields"]])
		self.assertIn("Leads", [x["kind"] for x in out["remove"]])

	def test_preview_shape(self):
		self.r.append("checklist", {"description": "Delete the export"})
		self.r.append("checklist", {"description": "Already done", "done": 1})
		self.r.contract_references = "Contract 7"
		self.r.save()
		make_communication(sender=EMAIL)
		out = preview(plan_erasure(self.r))
		remove = {x["kind"]: x for x in out["remove"]}
		self.assertEqual(
			[x["kind"] for x in out["remove"]],
			["Leads", "Contacts", "Deals (still on)", "Addresses", "Emails", "Calls", "Notes", "Tasks", "Comments", "Files"],
		)
		self.assertEqual(remove["Leads"]["count"], 1)
		self.assertEqual(
			remove["Leads"]["links"], [{"doctype": "CRM Lead", "name": self.m.lead, "title": "Marisol Vega"}]
		)
		self.assertEqual(remove["Contacts"]["links"][0]["title"], "Marisol Vega")
		self.assertEqual(remove["Deals (still on)"]["links"][0]["name"], self.m.won_deal)
		self.assertEqual(remove["Emails"]["count"], 1)
		self.assertNotIn("links", remove["Emails"])
		keep = {x["label"]: x for x in out["keep"]}
		removed_label = "Open deals she was removed from (their notes, tasks, comments and files stay)"
		self.assertEqual([link["name"] for link in keep[removed_label]["links"]], [self.m.open_deal])
		self.assertEqual([link["name"] for link in keep["Organizations"]["links"]], [self.m.org])
		for label in (
			"Deal values, status and stage",
			"Lead and deal records as anonymized shells",
			"Email, call and note records as placeholders",
			"Retained-contract entry",
		):
			self.assertIn(label, keep)
		self.assertEqual(out["warnings"]["open_checklist"], ["Delete the export"])

	def test_preview_omits_retained_contract_without_references(self):
		out = preview(plan_erasure(self.r))
		self.assertNotIn("Retained-contract entry", [x["label"] for x in out["keep"]])

	def test_preview_endpoint_is_compliance_only(self):
		make_user("rep@example.com", ["Sales User", "Sales Manager"])
		frappe.set_user("rep@example.com")
		with self.assertRaises(frappe.PermissionError):
			get_erasure_preview(self.r.name)
		frappe.set_user(make_compliance_user())
		out = get_erasure_preview(self.r.name)
		self.assertEqual({"remove", "keep", "warnings"}, set(out))

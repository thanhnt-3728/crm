# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import make_request, make_user
from crm.privacy import system_write
from crm.privacy.preview import collect_targets, get_erasure_preview
from crm.privacy.setup import ensure_privacy_setup
from crm.tests.test_privacy_matching import OWNER, make_person

SAVEPOINT = "test_privacy_preview"
EMAIL = "marisol@x.net"
PHONE = "+19165550100"


def confirmed_request(lead, contact, deal, removed_from_deal=False, **values):
	"""A request with the person's lead, contact and deal confirmed. `removed_from_deal`
	marks the deal as one the person was taken off while the request was On Hold."""
	values.setdefault(
		"identifiers",
		[{"kind": "Email", "value": EMAIL}, {"kind": "Phone", "value": PHONE}],
	)
	request = make_request(**values)
	for doctype, name in (("CRM Lead", lead.name), ("Contact", contact.name), ("CRM Deal", deal.name)):
		request.append(
			"matches",
			{
				"reference_doctype": doctype,
				"reference_name": name,
				"confirmed": 1,
				"source": "Identifier match",
				"removed_from_open_deal": 1 if removed_from_deal and doctype == "CRM Deal" else 0,
			},
		)
	with system_write():
		request.save(ignore_permissions=True)
	return request


def make_communication(reference=None, links=(), **values):
	doc = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"subject": "Hello",
			"content": "Hello",
			**values,
		}
	)
	if reference:
		doc.reference_doctype, doc.reference_name = reference
	for link_doctype, link_name in links:
		doc.append("timeline_links", {"link_doctype": link_doctype, "link_name": link_name})
	return doc.insert(ignore_permissions=True)


def make_note(reference_doctype=None, reference_name=None, title="A note"):
	return frappe.get_doc(
		{
			"doctype": "FCRM Note",
			"title": title,
			"content": "Spoke about the contract",
			"reference_doctype": reference_doctype,
			"reference_docname": reference_name,
		}
	).insert(ignore_permissions=True)


def make_call_log(call_id, reference=None, **values):
	doc = frappe.get_doc(
		{
			"doctype": "CRM Call Log",
			"id": call_id,
			"from": "+14155550000",
			"to": "+14155550001",
			"type": "Outgoing",
			"status": "Completed",
			**values,
		}
	)
	if reference:
		doc.reference_doctype, doc.reference_docname = reference
	return doc.insert(ignore_permissions=True)


def remove_names(preview, kind):
	return [item["name"] for item in preview["remove"] if item["kind"] == kind]


class TestPrivacyPreview(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		make_user(OWNER, ["Sales User"])

	def setUp(self):
		frappe.db.savepoint(SAVEPOINT)
		# Phone numbers below are typed without a country code, so the site region must be US.
		frappe.db.set_single_value("System Settings", "country", "United States")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.privacy_system_write = False
		frappe.db.rollback(save_point=SAVEPOINT)

	def person(self, status="Won"):
		return make_person(EMAIL, PHONE, status=status)

	def test_preview_lists_lead_deal_contact_emails(self):
		lead, contact, deal = self.person()
		linked = make_communication(reference=("CRM Lead", lead.name), subject="On the lead")
		timeline = make_communication(links=[("CRM Deal", deal.name)], subject="On the deal timeline")
		by_address = make_communication(
			sender="Bob <bob@x.net>", recipients='"Marisol Vega" <Marisol@X.net>', subject="Anywhere"
		)
		make_communication(sender="bob@x.net", recipients="carol@x.net", subject="Unrelated")
		request = confirmed_request(lead, contact, deal)

		preview = get_erasure_preview(request.name)

		self.assertEqual(preview["counts"]["Email"], 3)
		self.assertEqual(
			sorted(remove_names(preview, "Email")),
			sorted([linked.name, timeline.name, by_address.name]),
		)
		self.assertEqual(preview["counts"]["Lead"], 1)
		self.assertEqual(preview["counts"]["Deal"], 1)
		self.assertEqual(preview["counts"]["Contact"], 1)
		self.assertEqual(remove_names(preview, "Lead"), [lead.name])
		self.assertEqual(remove_names(preview, "Deal"), [deal.name])
		first = preview["remove"][0]
		self.assertEqual(set(first), {"kind", "doctype", "name", "label"})

	def test_removed_from_open_deal_notes_are_kept(self):
		lead, contact, deal = self.person(status="Open")
		note = make_note("CRM Deal", deal.name, title="Open deal note")
		request = confirmed_request(lead, contact, deal, removed_from_deal=True)

		targets = collect_targets(request)
		self.assertEqual(targets.deals_removed_from, [deal.name])
		self.assertEqual(targets.deals_still_on, [])
		self.assertNotIn(note.name, targets.notes)

		preview = get_erasure_preview(request.name)
		self.assertNotIn(note.name, remove_names(preview, "Note"))
		self.assertEqual(preview["counts"]["Deal"], 0)
		self.assertTrue(any(deal.name in item["label"] for item in preview["keep"]))

	def test_removed_from_open_deal_emails_are_still_removed(self):
		lead, contact, deal = self.person(status="Open")
		by_address = make_communication(sender="Marisol@X.net", subject="Names her")
		on_deal = make_communication(reference=("CRM Deal", deal.name), subject="About the deal")
		request = confirmed_request(lead, contact, deal, removed_from_deal=True)

		emails = remove_names(get_erasure_preview(request.name), "Email")
		self.assertIn(by_address.name, emails)
		self.assertNotIn(on_deal.name, emails)

	def test_still_on_deal_notes_removed(self):
		lead, contact, deal = self.person()
		note = make_note("CRM Deal", deal.name)
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Call her back",
				"reference_doctype": "CRM Deal",
				"reference_docname": deal.name,
			}
		).insert(ignore_permissions=True)
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Deal",
				"reference_name": deal.name,
				"content": "She prefers email",
			}
		).insert(ignore_permissions=True)
		request = confirmed_request(lead, contact, deal)

		preview = get_erasure_preview(request.name)
		self.assertEqual(remove_names(preview, "Note"), [note.name])
		self.assertEqual(remove_names(preview, "Task"), [task.name])
		self.assertEqual(remove_names(preview, "Comment"), [comment.name])

	def test_targets_are_sorted_and_deduplicated(self):
		lead, contact, deal = self.person()
		# Matches by link and by address: still one entry.
		both = make_communication(reference=("CRM Lead", lead.name), sender=EMAIL)
		request = confirmed_request(lead, contact, deal)

		targets = collect_targets(request)
		self.assertEqual(targets.communications, [both.name])
		self.assertEqual(targets.leads, [lead.name])
		self.assertEqual(targets.contacts, [contact.name])
		for names in (targets.notes, targets.call_logs, targets.files, targets.addresses):
			self.assertEqual(names, sorted(set(names)))

	def test_files_and_photos_are_targets(self):
		lead, contact, deal = self.person()
		communication = make_communication(reference=("CRM Lead", lead.name))
		photo_url = "https://example.com/marisol.png"
		lead.db_set("image", photo_url)

		def make_file(name, **values):
			return frappe.get_doc(
				{"doctype": "File", "file_name": name, "file_url": f"https://example.com/{name}", **values}
			).insert(ignore_permissions=True)

		on_deal = make_file("proposal.pdf", attached_to_doctype="CRM Deal", attached_to_name=deal.name)
		on_email = make_file(
			"attachment.pdf", attached_to_doctype="Communication", attached_to_name=communication.name
		)
		photo = make_file("marisol.png")
		other = make_file("other.pdf", attached_to_doctype="CRM Deal", attached_to_name="CRM-DEAL-NOPE")
		request = confirmed_request(lead, contact, deal)

		files = collect_targets(request).files
		self.assertEqual(files, sorted([on_deal.name, on_email.name, photo.name]))
		self.assertNotIn(other.name, files)

	def test_address_of_contact_is_a_target(self):
		lead, contact, deal = self.person()
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Marisol home",
				"address_line1": "1 Main St",
				"city": "Sacramento",
				"country": "United States",
				"links": [{"link_doctype": "Contact", "link_name": contact.name}],
			}
		).insert(ignore_permissions=True)
		request = confirmed_request(lead, contact, deal)

		preview = get_erasure_preview(request.name)
		self.assertEqual(remove_names(preview, "Address"), [address.name])
		self.assertEqual(preview["counts"]["Address"], 1)

	def test_call_logs_and_their_notes_are_targets(self):
		lead, contact, deal = self.person()
		note = make_note(title="Written on the call")
		linked = make_call_log("preview-call-1", reference=("CRM Lead", lead.name), note=note.name)
		by_phone = make_call_log("preview-call-2", **{"from": "(916) 555-0100"})
		make_call_log("preview-call-3")
		request = confirmed_request(lead, contact, deal)

		preview = get_erasure_preview(request.name)
		self.assertEqual(sorted(remove_names(preview, "Call")), sorted([linked.name, by_phone.name]))
		self.assertIn(note.name, remove_names(preview, "Note"))

	def test_recordings_present(self):
		lead, contact, deal = self.person()
		request = confirmed_request(lead, contact, deal)
		self.assertFalse(get_erasure_preview(request.name)["recordings_present"])

		make_call_log(
			"preview-call-rec",
			reference=("CRM Lead", lead.name),
			recording_url="https://api.twilio.com/recordings/RE123",
		)
		preview = get_erasure_preview(request.name)
		self.assertTrue(preview["recordings_present"])
		self.assertTrue(any("Twilio" in item for item in preview["open_checklist"]))

	def test_open_checklist_lists_only_undone_items(self):
		lead, contact, deal = self.person()
		request = confirmed_request(
			lead,
			contact,
			deal,
			checklist=[
				{"description": "Delete backups", "done": 0},
				{"description": "Tell the mailing vendor", "done": 1},
			],
		)
		self.assertEqual(get_erasure_preview(request.name)["open_checklist"], ["Delete backups"])

	def test_keep_lists_organization_shells_placeholders_and_contract(self):
		lead, contact, deal = self.person()
		make_communication(reference=("CRM Lead", lead.name))
		request = confirmed_request(lead, contact, deal, contract_references="MSA-2025-014")

		keep = get_erasure_preview(request.name)["keep"]
		labels = " | ".join(item["label"] for item in keep)
		self.assertIn("Matching Test Org", labels)
		self.assertIn("Anonymized shells", labels)
		self.assertIn("Placeholder records", labels)
		self.assertIn("MSA-2025-014", labels)
		self.assertTrue(all(item["reason"] for item in keep))


class TestPrivacyPreviewCustomFields(IntegrationTestCase):
	"""Creating a Custom Field alters the table, and that commits: it would release a
	savepoint taken in setUp. So this class takes no savepoint up front. The test creates the
	fields first, takes a savepoint after the commit, and removes the fields explicitly."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.privacy_system_write = False

	def add_custom_field(self, doctype, values):
		create_custom_field(doctype, values)
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": values["fieldname"]})
		self.addCleanup(frappe.delete_doc, "Custom Field", name, force=True, ignore_permissions=True)

	def test_unlisted_custom_field_flagged(self):
		# Cleanups run last in, first out: roll back the request, delete the fields, then
		# clear the cache and commit the deletions.
		self.addCleanup(frappe.db.commit)
		self.addCleanup(frappe.clear_cache, doctype="CRM Lead")
		self.add_custom_field(
			"CRM Lead",
			{"fieldname": "personal_mobile", "fieldtype": "Data", "label": "Personal mobile"},
		)
		self.add_custom_field("CRM Lead", {"fieldname": "is_vip", "fieldtype": "Check", "label": "Is VIP"})
		frappe.clear_cache(doctype="CRM Lead")
		frappe.db.commit()

		# The fields are committed; everything from here on is rolled back.
		frappe.db.savepoint(SAVEPOINT)
		self.addCleanup(frappe.db.rollback, save_point=SAVEPOINT)
		request = make_request(identifiers=[{"kind": "Email", "value": EMAIL}])

		flagged = get_erasure_preview(request.name)["unlisted_custom_fields"]
		fieldnames = [f["fieldname"] for f in flagged]
		self.assertIn("personal_mobile", fieldnames)
		self.assertNotIn("is_vip", fieldnames)
		field = next(f for f in flagged if f["fieldname"] == "personal_mobile")
		self.assertEqual(field["doctype"], "CRM Lead")
		self.assertEqual(field["label"], "Personal mobile")

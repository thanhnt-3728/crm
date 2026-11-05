# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import make_request, make_user
from crm.privacy import system_write
from crm.privacy.matching import (
	active_identifiers,
	confirmed,
	open_deals_with_person,
	refresh_identifiers,
	submit_request,
	suggest_matches,
)
from crm.privacy.setup import ensure_privacy_setup

OWNER = "matching-owner@example.com"
OTHER_OWNER = "matching-other-owner@example.com"
SAVEPOINT = "test_privacy_matching"


def ensure_deal_status(name, status_type):
	if not frappe.db.exists("CRM Deal Status", name):
		frappe.get_doc({"doctype": "CRM Deal Status", "deal_status": name, "type": status_type}).insert(
			ignore_permissions=True
		)
	return name


def ensure_lost_reason(name="Pricing"):
	"""A deal with a Lost status type cannot be saved without a lost reason."""
	if not frappe.db.exists("CRM Lost Reason", name):
		frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": name}).insert(ignore_permissions=True)
	return name


def make_person(email, phone, owner=OWNER, status="Open", first_name="Marisol"):
	"""A lead, a contact and a deal for one person: the deal was converted from the lead and
	lists the contact."""
	lead = frappe.get_doc(
		{"doctype": "CRM Lead", "first_name": first_name, "email": email, "mobile_no": phone}
	)
	lead.flags.ignore_mandatory = True
	lead.insert(ignore_permissions=True)

	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": first_name,
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"phone_nos": [{"phone": phone, "is_primary_mobile_no": 1}],
		}
	).insert(ignore_permissions=True)

	deal = frappe.get_doc(
		{
			"doctype": "CRM Deal",
			"deal_owner": owner,
			"organization": "Matching Test Org",
			"status": ensure_deal_status(f"Matching {status}", status),
			"lead": lead.name,
			"contacts": [{"contact": contact.name}],
		}
	)
	if status == "Lost":
		deal.lost_reason = ensure_lost_reason()
	deal.flags.ignore_mandatory = True
	deal.flags.ignore_links = True
	deal.insert(ignore_permissions=True)
	return lead, contact, deal


def confirm_contact(request, contact):
	request.append(
		"matches",
		{
			"reference_doctype": "Contact",
			"reference_name": contact.name,
			"confirmed": 1,
			"source": "Started from",
		},
	)


def confirm_all(request):
	for row in request.matches:
		row.confirmed = 1
	request.save(ignore_permissions=True)


class TestPrivacyMatching(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		make_user(OWNER, ["Sales User"])
		make_user(OTHER_OWNER, ["Sales User"])

	def setUp(self):
		frappe.db.savepoint(SAVEPOINT)
		# Phone numbers below are typed without a country code, so the site region must be US.
		frappe.db.set_single_value("System Settings", "country", "United States")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.privacy_system_write = False
		frappe.db.rollback(save_point=SAVEPOINT)

	def status_of(self, request):
		return frappe.db.get_value("CRM Erasure Request", request.name, "status")

	def held_request(self, **person):
		"""A request on hold: she is a confirmed contact on an open deal."""
		lead, contact, deal = make_person("marisol@x.net", "+19165550100", **person)
		request = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		confirm_contact(request, contact)
		request.save(ignore_permissions=True)
		self.assertEqual(submit_request(request.name), "On Hold")
		return request, lead, contact, deal

	# -- suggestions -----------------------------------------------------------------------

	def test_suggests_by_email_and_linked_deals(self):
		lead, contact, deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "Marisol@X.net"}])
		suggest_matches(r)
		found = {(m.reference_doctype, m.reference_name) for m in r.matches}
		self.assertIn(("CRM Lead", lead.name), found)
		self.assertIn(("Contact", contact.name), found)
		self.assertIn(("CRM Deal", deal.name), found)
		self.assertFalse(any(m.confirmed for m in r.matches))

	def test_linked_deal_of_confirmed_lead_is_suggested_by_link(self):
		lead, _contact, deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "nobody@nowhere.example"}])
		r.append(
			"matches",
			{"reference_doctype": "CRM Lead", "reference_name": lead.name, "confirmed": 1},
		)
		suggest_matches(r)
		deal_row = next(m for m in r.matches if m.reference_doctype == "CRM Deal")
		self.assertEqual(deal_row.reference_name, deal.name)
		self.assertEqual(deal_row.source, "Linked record")

	def test_suggests_by_phone_typed_differently(self):
		lead, _contact, _deal = make_person("marisol@x.net", "(916) 555-0100")
		for typed in ("916.555.0100", "+19165550100", "(916) 555-0100"):
			r = make_request(identifiers=[{"kind": "Phone", "value": typed}])
			suggest_matches(r)
			found = {(m.reference_doctype, m.reference_name) for m in r.matches}
			self.assertIn(("CRM Lead", lead.name), found, typed)

	def test_does_not_suggest_other_people(self):
		make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "someone.else@x.net"}])
		suggest_matches(r)
		self.assertEqual(len(r.matches), 0)

	def test_excluded_identifier_not_used(self):
		_lead, _contact, _deal = make_person("office@x.net", "+19165550199")
		r = make_request(
			identifiers=[
				{"kind": "Email", "value": "office@x.net", "excluded": 1},
				{"kind": "Phone", "value": "916-555-0199", "excluded": 1},
			]
		)
		suggest_matches(r)
		self.assertEqual(len(r.matches), 0)
		self.assertEqual(active_identifiers(r, "Email"), [])
		self.assertEqual(active_identifiers(r, "Phone"), [])

	def test_never_duplicates_existing_rows(self):
		_lead, contact, _deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		r.append(
			"matches",
			{
				"reference_doctype": "Contact",
				"reference_name": contact.name,
				"confirmed": 1,
				"source": "Started from",
			},
		)
		suggest_matches(r)
		count = len(r.matches)
		suggest_matches(r)
		self.assertEqual(len(r.matches), count)
		contact_rows = [m for m in r.matches if m.reference_doctype == "Contact"]
		self.assertEqual(len(contact_rows), 1)
		self.assertEqual(contact_rows[0].confirmed, 1)

	def test_active_identifiers_are_normalized_and_deduplicated(self):
		r = make_request(
			identifiers=[
				{"kind": "Email", "value": " Marisol@X.net "},
				{"kind": "Email", "value": "marisol@x.net"},
				{"kind": "Phone", "value": "(916) 555-0100"},
				{"kind": "Phone", "value": "+19165550100"},
			]
		)
		self.assertEqual(active_identifiers(r, "Email"), ["marisol@x.net"])
		self.assertEqual(active_identifiers(r, "Phone"), ["+19165550100"])

	def test_confirmed_lists_only_confirmed_rows_of_the_doctype(self):
		lead, contact, _deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		r.append("matches", {"reference_doctype": "Contact", "reference_name": contact.name, "confirmed": 1})
		r.append("matches", {"reference_doctype": "CRM Lead", "reference_name": lead.name, "confirmed": 0})
		self.assertEqual(confirmed(r, "Contact"), [contact.name])
		self.assertEqual(confirmed(r, "CRM Lead"), [])

	# -- identifiers -----------------------------------------------------------------------

	def test_refresh_identifiers_adds_contact_phone_and_counts(self):
		_lead, contact, _deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		confirm_contact(r, contact)
		refresh_identifiers(r)
		phones = [row for row in r.identifiers if row.kind == "Phone"]
		self.assertEqual([row.value for row in phones], ["+19165550100"])
		self.assertGreaterEqual(phones[0].match_count, 1)
		email = next(row for row in r.identifiers if row.kind == "Email")
		self.assertGreaterEqual(email.match_count, 1)
		# no repeats on a second run
		refresh_identifiers(r)
		self.assertEqual(len(r.identifiers), 2)

	def test_refresh_identifiers_adds_confirmed_lead_values(self):
		lead, _contact, _deal = make_person("marisol@x.net", "(916) 555-0100")
		r = make_request(identifiers=[{"kind": "Email", "value": "other@x.net"}])
		r.append("matches", {"reference_doctype": "CRM Lead", "reference_name": lead.name, "confirmed": 1})
		refresh_identifiers(r)
		self.assertIn("marisol@x.net", active_identifiers(r, "Email"))
		self.assertIn("+19165550100", active_identifiers(r, "Phone"))

	def test_refresh_identifiers_keeps_an_excluded_identifier_excluded(self):
		_lead, contact, _deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Phone", "value": "916-555-0100", "excluded": 1}])
		confirm_contact(r, contact)
		refresh_identifiers(r)
		phones = [row for row in r.identifiers if row.kind == "Phone"]
		self.assertEqual(len(phones), 1)
		self.assertEqual(phones[0].excluded, 1)
		self.assertEqual(active_identifiers(r, "Phone"), [])

	def test_match_count_includes_communications_and_call_logs(self):
		make_person("marisol@x.net", "+19165550100")
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Hello",
				"sender": "Bob <bob@x.net>",
				"recipients": '"Marisol Vega" <Marisol@X.net>, carol@x.net',
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": "matching-call-1",
				"from": "(916) 555-0100",
				"to": "+14155550000",
				"type": "Incoming",
				"status": "Completed",
			}
		).insert(ignore_permissions=True)

		r = make_request(
			identifiers=[
				{"kind": "Email", "value": "marisol@x.net"},
				{"kind": "Phone", "value": "+1 916 555 0100"},
			]
		)
		refresh_identifiers(r)
		email = next(row for row in r.identifiers if row.kind == "Email")
		phone = next(row for row in r.identifiers if row.kind == "Phone")
		# lead + contact + deal + the one Communication
		self.assertGreaterEqual(email.match_count, 4)
		# lead + contact + the one call log
		self.assertGreaterEqual(phone.match_count, 3)

	# -- On Hold ---------------------------------------------------------------------------

	def test_open_deals_with_person(self):
		_lead, contact, deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		self.assertEqual(open_deals_with_person(r), [])  # nothing confirmed
		confirm_contact(r, contact)
		self.assertEqual(open_deals_with_person(r), [deal.name])

	def test_deal_status_types(self):
		for status_type, is_open in (
			("Open", True),
			("Ongoing", True),
			("On Hold", True),
			("Won", False),
			("Lost", False),
		):
			_lead, contact, deal = make_person(
				f"{status_type.replace(' ', '').lower()}@x.net", "+19165550100", status=status_type
			)
			r = make_request(identifiers=[{"kind": "Email", "value": "x@x.net"}])
			confirm_contact(r, contact)
			self.assertEqual(open_deals_with_person(r), [deal.name] if is_open else [], status_type)

	def test_open_deal_puts_request_on_hold_and_notifies_owner(self):
		r, _lead, contact, deal = self.held_request()
		self.assertEqual(self.status_of(r), "On Hold")
		notification = frappe.db.get_value(
			"CRM Notification",
			{"to_user": deal.deal_owner, "type": "Privacy", "reference_name": deal.name},
			["notification_text", "message"],
			as_dict=True,
		)
		self.assertTrue(notification)
		self.assertIn(
			f"Remove the requester from {deal.name} or close it — erasure request {r.name}",
			notification.notification_text,
		)
		self.assertIn(r.name, notification.message)
		# The notice outlives the erasure: it names the request and the deal, never the person.
		for text in (notification.notification_text, notification.message):
			self.assertNotIn(contact.first_name, text)
			self.assertNotIn("marisol", text.lower())
		email = frappe.get_all(
			"Email Queue", filters={"message": ["like", f"%{r.name}%"]}, pluck="message", limit=1
		)
		for message in email:
			self.assertNotIn("Marisol", message)

	def test_no_open_deal_awaits_sign_off(self):
		_lead, contact, _deal = make_person("marisol@x.net", "+19165550100", status="Won")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		confirm_contact(r, contact)
		r.save(ignore_permissions=True)
		self.assertEqual(submit_request(r.name), "Awaiting Sign-off")
		self.assertEqual(self.status_of(r), "Awaiting Sign-off")

	def test_each_deal_owner_is_notified_once_per_deal(self):
		_lead, contact, deal = make_person("marisol@x.net", "+19165550100")
		_lead2, _contact2, other = make_person("other@x.net", "+19165550111", owner=OTHER_OWNER)
		other.append("contacts", {"contact": contact.name})
		other.save(ignore_permissions=True)
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		confirm_contact(r, contact)
		r.save(ignore_permissions=True)
		self.assertEqual(submit_request(r.name), "On Hold")
		for owner, name in ((OWNER, deal.name), (OTHER_OWNER, other.name)):
			self.assertEqual(
				frappe.db.count(
					"CRM Notification", {"to_user": owner, "type": "Privacy", "reference_name": name}
				),
				1,
			)

	def test_submit_requires_a_confirmed_match(self):
		make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		suggest_matches(r)
		r.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			submit_request(r.name)
		self.assertEqual(self.status_of(r), "Logged")

	def test_submit_only_from_logged(self):
		r, *_ = self.held_request()
		with self.assertRaises(frappe.ValidationError):
			submit_request(r.name)

	def test_removing_her_from_deal_releases_hold(self):
		r, _lead, contact, deal = self.held_request()
		deal.contacts = [row for row in deal.contacts if row.contact != contact.name]
		deal.save()
		self.assertEqual(self.status_of(r), "Awaiting Sign-off")

	def test_removing_her_marks_the_deal_match_row(self):
		_lead, contact, deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		suggest_matches(r)
		confirm_all(r)
		self.assertEqual(submit_request(r.name), "On Hold")

		deal.contacts = [row for row in deal.contacts if row.contact != contact.name]
		deal.save()

		rows = frappe.get_all(
			"CRM Erasure Match",
			filters={"parent": r.name, "reference_doctype": "CRM Deal"},
			fields=["reference_name", "removed_from_open_deal"],
		)
		self.assertEqual([(row.reference_name, row.removed_from_open_deal) for row in rows], [(deal.name, 1)])

	def test_closing_deal_lost_releases_hold(self):
		r, _lead, _contact, deal = self.held_request()
		deal.status = ensure_deal_status("Matching Lost", "Lost")
		deal.lost_reason = ensure_lost_reason()
		deal.save()
		self.assertEqual(self.status_of(r), "Awaiting Sign-off")
		# she is still on the deal, so its match row is not marked as removed
		self.assertFalse(
			frappe.db.exists("CRM Erasure Match", {"parent": r.name, "removed_from_open_deal": 1})
		)

	def test_hold_stays_while_another_open_deal_has_her(self):
		r, _lead, contact, deal = self.held_request()
		_lead2, _contact2, other = make_person("other@x.net", "+19165550111")
		other.append("contacts", {"contact": contact.name})
		other.save(ignore_permissions=True)
		# the new deal's own save re-checked and kept the hold; now take her off the first deal
		deal.contacts = [row for row in deal.contacts if row.contact != contact.name]
		deal.save()
		self.assertEqual(self.status_of(r), "On Hold")
		self.assertEqual(open_deals_with_person(frappe.get_doc("CRM Erasure Request", r.name)), [other.name])

	def test_deal_save_leaves_other_statuses_alone(self):
		_lead, contact, deal = make_person("marisol@x.net", "+19165550100")
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@x.net"}])
		confirm_contact(r, contact)
		with system_write():
			r.status = "Awaiting Sign-off"
			r.save(ignore_permissions=True)
		deal.save()
		self.assertEqual(self.status_of(r), "Awaiting Sign-off")

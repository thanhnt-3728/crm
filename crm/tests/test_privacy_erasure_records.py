# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json

import frappe
from frappe.tests import IntegrationTestCase

from crm.api import dashboard
from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import make_request, make_user
from crm.privacy import system_write
from crm.privacy.erasure import (
	erase_person_values,
	erase_records,
	placeholder_content,
	placeholder_person,
	scrub_version_data,
)
from crm.privacy.preview import collect_targets
from crm.privacy.setup import ensure_privacy_setup
from crm.tests.test_privacy_matching import OWNER, ensure_deal_status, make_person

SAVEPOINT = "test_privacy_erasure_records"
EMAIL = "marisol@x.net"
NEW_EMAIL = "marisol.vega@x.net"
PHONE = "+19165550100"
BOB_EMAIL = "bob@x.net"
BOB_PHONE = "+14155550123"
LINKEDIN = "https://www.linkedin.com/in/marisol-vega"

FROM_DATE = "2000-01-01"
TO_DATE = "2099-12-31"
DASHBOARD_FUNCTIONS = (
	"get_total_leads",
	"get_ongoing_deals",
	"get_average_ongoing_deal_value",
	"get_won_deals",
	"get_average_won_deal_value",
	"get_average_deal_value",
	"get_average_time_to_close_a_lead",
	"get_average_time_to_close_a_deal",
	"get_sales_trend",
	"get_forecasted_revenue",
	"get_funnel_conversion",
	"get_deals_by_stage_axis",
	"get_deals_by_stage_donut",
	"get_lost_deal_reasons",
	"get_leads_by_source",
	"get_deals_by_source",
	"get_deals_by_territory",
	"get_deals_by_salesperson",
)


def snapshot_dashboard():
	"""Every dashboard number over a wide date range, as the current user (Administrator)."""
	return {name: getattr(dashboard, name)(FROM_DATE, TO_DATE) for name in DASHBOARD_FUNCTIONS}


def make_contact(first_name, email, phone):
	return frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": first_name,
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"phone_nos": [{"phone": phone, "is_primary_mobile_no": 1}],
		}
	).insert(ignore_permissions=True)


def save_deal(deal):
	deal.flags.ignore_mandatory = True
	deal.flags.ignore_links = True
	deal.save(ignore_permissions=True)
	return deal


def other_lead_status(current):
	others = frappe.get_all(
		"CRM Lead Status", filters={"name": ["!=", current], "type": "Open"}, pluck="name"
	)
	if others:
		return others[0]
	return (
		frappe.get_doc(
			{"doctype": "CRM Lead Status", "lead_status": "Erasure Test Contacted", "type": "Open"}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_deleted_copy(doctype, data):
	return frappe.get_doc(
		{
			"doctype": "Deleted Document",
			"deleted_doctype": doctype,
			"deleted_name": frappe.generate_hash(length=10),
			"data": json.dumps(data),
		}
	).insert(ignore_permissions=True)


class TestPrivacyErasureRecords(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		make_user(OWNER, ["Sales User"])

	def setUp(self):
		frappe.db.savepoint(SAVEPOINT)
		# Phone numbers below are typed without a country code, so the site region must be US.
		frappe.db.set_single_value("System Settings", "country", "United States")
		self.build_person()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.privacy_system_write = False
		frappe.db.rollback(save_point=SAVEPOINT)

	def build_person(self):
		"""Marisol: a lead, a contact with an address, a Won deal of her own (she is its only
		contact), and Bob's Won deal she was added to later as a non-primary contact. Her lead
		and Bob's deal have change history that names her."""
		self.lead, self.contact, self.own_deal = make_person(EMAIL, PHONE, status="Won")
		frappe.db.set_value("CRM Lead", self.lead.name, "linkedin", LINKEDIN)
		frappe.db.set_value("CRM Deal", self.own_deal.name, {"deal_value": 1200, "first_name": "Marisol"})

		# Version: email and status changed in one save.
		lead = frappe.get_doc("CRM Lead", self.lead.name)
		self.original_status = other_lead_status(lead.status)
		lead.email = NEW_EMAIL
		lead.status = self.original_status
		lead.flags.ignore_mandatory = True
		lead.save(ignore_permissions=True)

		self.bob = make_contact("Bob", BOB_EMAIL, BOB_PHONE)
		bob_deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"deal_owner": OWNER,
				"organization": "Matching Test Org",
				"status": ensure_deal_status("Matching Won", "Won"),
				"deal_value": 3400,
				"contacts": [{"contact": self.bob.name, "is_primary": 1}],
			}
		)
		bob_deal.flags.ignore_mandatory = True
		bob_deal.flags.ignore_links = True
		bob_deal.insert(ignore_permissions=True)
		# Version: "added" row for Marisol on the contacts table.
		bob_deal.append("contacts", {"contact": self.contact.name, "is_primary": 0})
		self.bob_deal = save_deal(bob_deal)

		self.address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Marisol Vega",
				"address_type": "Billing",
				"address_line1": "12 Elm Street",
				"city": "Sacramento",
				"country": "United States",
				"email_id": EMAIL,
				"links": [{"link_doctype": "Contact", "link_name": self.contact.name}],
			}
		).insert(ignore_permissions=True)

		self.request = make_request(
			requester_names="Marisol Vega",
			identifiers=[{"kind": "Email", "value": EMAIL}, {"kind": "Phone", "value": "(916) 555-0100"}],
		)
		for doctype, name in (
			("CRM Lead", self.lead.name),
			("Contact", self.contact.name),
			("CRM Deal", self.own_deal.name),
			("CRM Deal", self.bob_deal.name),
		):
			self.request.append(
				"matches",
				{
					"reference_doctype": doctype,
					"reference_name": name,
					"confirmed": 1,
					"source": "Identifier match",
				},
			)
		with system_write():
			self.request.save(ignore_permissions=True)

	def erase(self):
		erase_records(self.request, collect_targets(self.request))

	@property
	def person(self):
		return placeholder_person(self.request.name)

	@property
	def new_contact(self):
		return placeholder_person(self.request.name)

	@property
	def new_address(self):
		return f"{placeholder_person(self.request.name)}-Address"

	def versions_of(self, doctype, name):
		return frappe.get_all("Version", filters={"ref_doctype": doctype, "docname": name}, pluck="data")

	# -- placeholders and pure helpers ---------------------------------------------------

	def test_placeholders(self):
		self.assertEqual(placeholder_person("PDR-0001"), "Erased person PDR-0001")
		self.assertEqual(placeholder_content("PDR-0001"), "Content erased PDR-0001")

	def test_scrub_version_data_pure(self):
		data = {"changed": [["email", "m@x.net", "n@x.net"], ["status", "New", "Contacted"]]}
		out = scrub_version_data(data, {"email"}, "Erased person PDR-0001")
		self.assertEqual(
			out["changed"],
			[["email", "Erased person PDR-0001", "Erased person PDR-0001"], ["status", "New", "Contacted"]],
		)
		# The input is left alone.
		self.assertEqual(data["changed"][0], ["email", "m@x.net", "n@x.net"])

	def test_scrub_version_data_tables(self):
		data = {
			"changed": [["email", None, "m@x.net"]],
			"added": [["contacts", {"contact": "C-1", "email": "m@x.net", "is_primary": 0}]],
			"removed": [["products", {"product_name": "Widget", "email": "keep@x.net"}]],
			"row_changed": [["contacts", 0, "row1", [["mobile_no", "1", "2"], ["is_primary", 0, 1]]]],
		}
		out = scrub_version_data(data, {"email"}, "P", tables={"contacts": {"email", "mobile_no"}})
		self.assertEqual(out["changed"], [["email", None, "P"]])
		self.assertEqual(out["added"][0][1], {"contact": "C-1", "email": "P", "is_primary": 0})
		self.assertEqual(out["removed"][0][1]["email"], "keep@x.net")
		self.assertEqual(out["row_changed"][0][3], [["mobile_no", "P", "P"], ["is_primary", 0, 1]])

	def test_erase_person_values(self):
		values = erase_person_values(self.request)
		self.assertIn(EMAIL, values)
		self.assertIn(NEW_EMAIL, values)
		self.assertIn(PHONE, values)
		self.assertIn("Marisol", values)
		self.assertIn("Marisol Vega", values)
		self.assertNotIn(BOB_EMAIL, values)

	# -- records ---------------------------------------------------------------------------

	def test_dashboard_numbers_unchanged(self):
		before = snapshot_dashboard()
		self.erase()
		self.assertEqual(before, snapshot_dashboard())

	def test_lead_blanked_with_placeholder(self):
		self.erase()
		lead = frappe.get_doc("CRM Lead", self.lead.name)
		self.assertEqual(lead.first_name, self.person)
		self.assertEqual(lead.lead_name, self.person)
		self.assertFalse(lead.email or lead.mobile_no or lead.linkedin or lead.image)
		self.assertEqual(lead.status, self.original_status)

	def test_contact_blanked_and_child_rows_removed(self):
		self.erase()
		contact = frappe.get_doc("Contact", self.new_contact)
		self.assertEqual(contact.first_name, self.person)
		self.assertEqual(contact.full_name, self.person)
		self.assertFalse(contact.email_id or contact.mobile_no or contact.phone)
		self.assertFalse(frappe.db.exists("Contact Email", {"parent": self.new_contact}))
		self.assertFalse(frappe.db.exists("Contact Phone", {"parent": self.new_contact}))
		# Bob keeps his details.
		self.assertTrue(frappe.db.exists("Contact Email", {"parent": self.bob.name, "email_id": BOB_EMAIL}))

	def test_address_blanked(self):
		self.erase()
		address = frappe.db.get_value(
			"Address", self.new_address, ["address_title", "address_line1", "city", "email_id"], as_dict=True
		)
		self.assertEqual(address.address_title, self.person)
		self.assertFalse(address.address_line1 or address.city or address.email_id)
		# The link row to the renamed contact no longer carries her name as its title.
		titles = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Address", "parent": self.new_address, "link_doctype": "Contact"},
			fields=["link_name", "link_title"],
			parent_doctype="Address",
		)
		self.assertEqual([(t.link_name, t.link_title) for t in titles], [(self.new_contact, self.person)])

	def test_shared_address_keeps_fields_and_loses_only_her_link(self):
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Erasure Shared Org"}
		).insert(ignore_permissions=True)
		shared = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Shared Office",
				"address_type": "Office",
				"address_line1": "1 Market Street",
				"city": "Sacramento",
				"country": "United States",
				"links": [
					{"link_doctype": "Contact", "link_name": self.contact.name},
					{"link_doctype": "CRM Organization", "link_name": org.name},
				],
			}
		).insert(ignore_permissions=True)
		targets = collect_targets(self.request)
		self.assertIn(shared.name, targets.addresses)

		erase_records(self.request, targets)

		self.assertNotIn(shared.name, targets.addresses)
		values = frappe.db.get_value(
			"Address", shared.name, ["address_title", "address_line1", "city"], as_dict=True
		)
		self.assertEqual(
			(values.address_title, values.address_line1, values.city),
			("Shared Office", "1 Market Street", "Sacramento"),
		)
		links = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Address", "parent": shared.name},
			fields=["link_doctype", "link_name"],
			parent_doctype="Address",
		)
		self.assertEqual(
			[(link.link_doctype, link.link_name) for link in links], [("CRM Organization", org.name)]
		)

	def test_own_deal_personal_fields_blanked_values_kept(self):
		self.erase()
		deal = frappe.get_doc("CRM Deal", self.own_deal.name)
		self.assertFalse(deal.email or deal.mobile_no or deal.first_name)
		self.assertEqual(deal.deal_value, 1200)
		self.assertEqual(deal.status, self.own_deal.status)
		self.assertEqual([c.full_name for c in deal.contacts], [self.person])
		self.assertEqual([c.contact for c in deal.contacts], [self.new_contact])

	def test_non_primary_contact_on_deal_primary_untouched(self):
		self.erase()
		deal = frappe.get_doc("CRM Deal", self.bob_deal.name)
		self.assertEqual(deal.email, BOB_EMAIL)
		self.assertEqual(deal.mobile_no, BOB_PHONE)
		self.assertEqual([c.full_name for c in deal.contacts if c.contact == self.new_contact], [self.person])
		hers = next(c for c in deal.contacts if c.contact == self.new_contact)
		self.assertFalse(hers.email or hers.mobile_no or hers.phone)
		bobs = next(c for c in deal.contacts if c.contact == self.bob.name)
		self.assertEqual((bobs.full_name, bobs.email), ("Bob", BOB_EMAIL))

	def test_generic_deal_fields_blanked_only_with_her_details(self):
		same = {"gender": "Female", "salutation": "Ms", "job_title": "CEO"}
		frappe.db.set_value("CRM Lead", self.lead.name, same)
		frappe.db.set_value("CRM Deal", self.own_deal.name, same)
		frappe.db.set_value("CRM Deal", self.bob_deal.name, same)
		self.erase()
		# Her own deal: she is its primary contact, so these are hers.
		own = frappe.db.get_value("CRM Deal", self.own_deal.name, list(same), as_dict=True)
		self.assertFalse(own.gender or own.salutation or own.job_title)
		# Bob is primary on the shared deal: equal values may well be Bob's, so they stay.
		bobs = frappe.db.get_value("CRM Deal", self.bob_deal.name, list(same), as_dict=True)
		self.assertEqual(dict(bobs), same)

	def test_shared_deal_last_name_alone_kept(self):
		frappe.db.set_value("CRM Lead", self.lead.name, "last_name", "Vega")
		frappe.db.set_value("CRM Deal", self.bob_deal.name, {"first_name": "Rosa", "last_name": "Vega"})
		self.erase()
		self.assertEqual(frappe.db.get_value("CRM Deal", self.bob_deal.name, "last_name"), "Vega")

	# -- renaming ------------------------------------------------------------------------

	def test_contact_renamed_to_placeholder(self):
		old = self.contact.name
		self.erase()
		self.assertFalse(frappe.db.exists("Contact", old))
		self.assertTrue(frappe.db.exists("Contact", self.new_contact))
		deal = frappe.get_doc("CRM Deal", self.bob_deal.name)
		self.assertIn(self.new_contact, [c.contact for c in deal.contacts])
		self.assertNotIn(old, [c.contact for c in deal.contacts])
		# The address keeps its link to the renamed contact.
		self.assertTrue(
			frappe.db.exists(
				"Dynamic Link",
				{"parent": self.new_address, "link_doctype": "Contact", "link_name": self.new_contact},
			)
		)
		# The request's match row follows the new name, in the database and in memory.
		self.assertIn(self.new_contact, [m.reference_name for m in self.request.matches])
		self.assertTrue(
			frappe.db.exists(
				"CRM Erasure Match",
				{
					"parent": self.request.name,
					"reference_doctype": "Contact",
					"reference_name": self.new_contact,
				},
			)
		)

	def test_address_renamed_to_placeholder(self):
		old = self.address.name
		self.erase()
		self.assertFalse(frappe.db.exists("Address", old))
		self.assertTrue(frappe.db.exists("Address", self.new_address))

	def test_several_contacts_get_numbered_names(self):
		second = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Marisol",
				"last_name": "Vega",
				"email_ids": [{"email_id": NEW_EMAIL}],
			}
		).insert(ignore_permissions=True)
		self.request.append(
			"matches",
			{
				"reference_doctype": "Contact",
				"reference_name": second.name,
				"confirmed": 1,
				"source": "Identifier match",
			},
		)
		with system_write():
			self.request.save(ignore_permissions=True)
		first, last = sorted([self.contact.name, second.name])
		self.erase()
		self.assertFalse(frappe.db.exists("Contact", first) or frappe.db.exists("Contact", last))
		self.assertTrue(frappe.db.exists("Contact", self.new_contact))
		self.assertTrue(frappe.db.exists("Contact", f"{self.new_contact}-2"))

	def test_rename_comment_removed(self):
		old_contact, old_address = self.contact.name, self.address.name
		self.erase()
		for doctype, old in (("Contact", old_contact), ("Address", old_address)):
			self.assertFalse(
				frappe.db.exists("Comment", {"reference_doctype": doctype, "content": ["like", f"%{old}%"]})
			)

	def test_version_link_values_renamed(self):
		old = self.contact.name
		# Bob's deal history holds the added contacts row, linking her contact by name.
		self.assertTrue(any(f'"{old}"' in data for data in self.versions_of("CRM Deal", self.bob_deal.name)))
		self.erase()
		for doctype, name in (
			("CRM Lead", self.lead.name),
			("CRM Deal", self.own_deal.name),
			("CRM Deal", self.bob_deal.name),
			("Contact", self.new_contact),
			("Address", self.new_address),
		):
			for data in self.versions_of(doctype, name):
				self.assertNotIn(f'"{old}"', data)
				self.assertNotIn(f'"{self.address.name}"', data)
		self.assertTrue(
			any(f'"{self.new_contact}"' in data for data in self.versions_of("CRM Deal", self.bob_deal.name))
		)

	# -- change history ------------------------------------------------------------------

	def test_versions_hold_her_details_before_erasure(self):
		# Guards the next test against passing for want of history.
		self.assertTrue(frappe.db.exists("Version", {"data": ["like", f"%{EMAIL}%"]}))

	def test_no_version_holds_email(self):
		self.erase()
		self.assertFalse(frappe.db.exists("Version", {"data": ["like", f"%{EMAIL}%"]}))
		self.assertFalse(frappe.db.exists("Version", {"data": ["like", f"%{NEW_EMAIL}%"]}))

	def test_version_keeps_non_personal_changes(self):
		self.erase()
		data = json.loads(
			frappe.get_all(
				"Version",
				filters={
					"ref_doctype": "CRM Lead",
					"docname": self.lead.name,
					"data": ["like", '%"status"%'],
				},
				pluck="data",
			)[0]
		)
		changed = {change[0]: change for change in data["changed"]}
		self.assertEqual(changed["status"][2], self.original_status)
		self.assertEqual(changed["email"][1:], [self.person, self.person])

	def test_shared_deal_version_keeps_bobs_changes(self):
		version = frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": "CRM Deal",
				"docname": self.bob_deal.name,
				"data": json.dumps(
					{
						"changed": [["email", "bob.old@x.net", BOB_EMAIL], ["email", EMAIL, BOB_EMAIL]],
						"added": [
							[
								"contacts",
								{
									"name": "bob-row",
									"contact": self.bob.name,
									"full_name": "Bob",
									"email": BOB_EMAIL,
								},
							]
						],
						"row_changed": [
							["contacts", 0, "bob-row", [["mobile_no", "+14155550000", BOB_PHONE]]]
						],
					}
				),
			}
		).insert(ignore_permissions=True)

		self.erase()

		data = json.loads(frappe.db.get_value("Version", version.name, "data"))
		self.assertEqual(
			data["changed"], [["email", "bob.old@x.net", BOB_EMAIL], ["email", self.person, BOB_EMAIL]]
		)
		self.assertEqual(
			data["added"][0][1],
			{"name": "bob-row", "contact": self.bob.name, "full_name": "Bob", "email": BOB_EMAIL},
		)
		self.assertEqual(data["row_changed"][0][3], [["mobile_no", "+14155550000", BOB_PHONE]])

	def test_no_new_version_rows_created(self):
		n = frappe.db.count("Version")
		self.erase()
		self.assertLessEqual(frappe.db.count("Version"), n)

	# -- deleted copies ------------------------------------------------------------------

	def test_deleted_document_copies_removed(self):
		by_email = make_deleted_copy("CRM Lead", {"first_name": "M", "email": "Marisol@X.net"})
		by_phone = make_deleted_copy("Communication", {"content": "Call me on (916) 555-0100"})
		bobs = make_deleted_copy("CRM Lead", {"first_name": "Bob", "email": BOB_EMAIL})
		other_doctype = make_deleted_copy("ToDo", {"description": f"Email {EMAIL}"})

		self.erase()

		self.assertFalse(frappe.db.exists("Deleted Document", by_email.name))
		self.assertFalse(frappe.db.exists("Deleted Document", by_phone.name))
		self.assertTrue(frappe.db.exists("Deleted Document", bobs.name))
		self.assertTrue(frappe.db.exists("Deleted Document", other_doctype.name))

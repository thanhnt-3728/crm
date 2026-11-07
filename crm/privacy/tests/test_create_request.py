# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""create_request: prefill from a lead, contact or deal, permission checks, identifier validation."""

import frappe

from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	make_contact,
	make_deal,
	make_lead,
	make_request,
)

DT = "CRM Erasure Request"


def doc_of(name):
	return frappe.get_doc(DT, name)


def identifiers(doc):
	return [(r.kind, r.normalized, r.source, r.source_doctype, r.source_name) for r in doc.identifiers]


def matches(doc):
	return [
		(r.reference_doctype, r.reference_name, r.confirmed, r.is_source, r.relation) for r in doc.matches
	]


class TestFromRecords(RequestTestCase):
	def log_from(self, user, doctype, name, **values):
		values = {"emails": None, "requester_names": None, **values}
		return doc_of(make_request(user, source_doctype=doctype, source_name=name, **values))

	def test_from_a_lead_pre_confirms_it_and_seeds_identifiers(self):
		lead = make_lead(self.logger, email="m.vega@acme.com", mobile_no="+1 530 555 0101")
		doc = self.log_from(self.logger, "CRM Lead", lead)
		self.assertEqual(matches(doc), [("CRM Lead", lead, 1, 1, "Direct")])
		self.assertEqual(
			identifiers(doc),
			[
				("Email", "m.vega@acme.com", "Record", "CRM Lead", lead),
				("Phone", "+15305550101", "Record", "CRM Lead", lead),
			],
		)
		self.assertEqual((doc.status, doc.logged_by, doc.channel), ("Logged", self.logger, "Email"))
		self.assertIn("Marisol", doc.requester_names)

	def test_typed_values_come_first_and_duplicates_collapse(self):
		lead = make_lead(self.logger, email="m.vega@acme.com")
		doc = self.log_from(
			self.logger,
			"CRM Lead",
			lead,
			emails=["Private@Home.com", " M.Vega@acme.com "],
			phones=["(530) 555-0199"],
			requester_names="Mari Vega",
		)
		self.assertEqual(
			[(r.kind, r.normalized, r.source) for r in doc.identifiers],
			[
				("Email", "private@home.com", "Typed"),
				("Email", "m.vega@acme.com", "Typed"),
				("Phone", "+15305550199", "Typed"),
			],
		)
		self.assertEqual(doc.requester_names, "Mari Vega")

	def test_from_a_contact_takes_every_email_and_phone(self):
		contact = make_contact(
			"Marisol", emails=["a@acme.com", "b@acme.com"], phones=["+15305550101", "+15305550102"]
		)
		doc = self.log_from(self.manager, "Contact", contact)
		self.assertEqual(matches(doc), [("Contact", contact, 1, 1, "Direct")])
		self.assertEqual(
			sorted(i[1] for i in identifiers(doc)),
			["+15305550101", "+15305550102", "a@acme.com", "b@acme.com"],
		)

	def test_from_a_deal_with_one_contact_confirms_deal_and_contact(self):
		contact = make_contact("Marisol", emails=["a@acme.com"])
		deal = make_deal([contact], owner=self.manager)
		doc = self.log_from(self.manager, "CRM Deal", deal)
		self.assertEqual(
			matches(doc), [("CRM Deal", deal, 1, 1, "Direct"), ("Contact", contact, 1, 1, "Direct")]
		)
		self.assertEqual([i[1] for i in identifiers(doc)], ["a@acme.com"])

	def test_a_deal_with_several_contacts_needs_the_chosen_one(self):
		first = make_contact("Marisol", emails=["a@acme.com"])
		second = make_contact("Other", emails=["o@acme.com"], last_name="Person")
		deal = make_deal([first, second], owner=self.manager)
		with self.assertRaises(frappe.ValidationError):
			self.log_from(self.manager, "CRM Deal", deal)
		doc = self.log_from(self.manager, "CRM Deal", deal, contact=second)
		self.assertEqual([m[:2] for m in matches(doc)], [("CRM Deal", deal), ("Contact", second)])
		self.assertEqual([i[1] for i in identifiers(doc)], ["o@acme.com"])

	def test_a_contact_that_is_not_on_the_deal_is_refused(self):
		on_deal = make_contact("Marisol", emails=["a@acme.com"])
		stranger = make_contact("Stranger", emails=["s@acme.com"], last_name="Else")
		deal = make_deal([on_deal], owner=self.manager)
		with self.assertRaises(frappe.ValidationError):
			self.log_from(self.manager, "CRM Deal", deal, contact=stranger)

	def test_a_deal_without_contacts_confirms_only_the_deal(self):
		deal = make_deal([], owner=self.manager)
		doc = self.log_from(self.manager, "CRM Deal", deal)
		self.assertEqual(matches(doc), [("CRM Deal", deal, 1, 1, "Direct")])


class TestPermissionsAndValidation(RequestTestCase):
	def test_a_user_who_cannot_read_the_source_is_refused(self):
		lead = make_lead(self.logger, email="m.vega@acme.com")
		with self.assertRaises(frappe.PermissionError):
			make_request(self.other, source_doctype="CRM Lead", source_name=lead, emails=None)

	def test_a_sales_manager_can_log_from_someone_elses_lead(self):
		lead = make_lead(self.logger, email="m.vega@acme.com")
		name = make_request(self.manager, source_doctype="CRM Lead", source_name=lead, emails=None)
		self.assertEqual(doc_of(name).logged_by, self.manager)

	def test_unsupported_or_incomplete_sources_are_refused(self):
		for kwargs in (
			{"source_doctype": "User", "source_name": self.logger},
			{"source_doctype": "CRM Lead", "source_name": None},
			{"source_doctype": "CRM Lead", "source_name": "NO-SUCH-LEAD"},
		):
			with (
				self.subTest(**kwargs),
				self.assertRaises((frappe.ValidationError, frappe.DoesNotExistError)),
			):
				make_request(self.logger, emails=None, **kwargs)

	def test_malformed_identifiers_are_refused_and_nothing_is_created(self):
		before = frappe.db.count(DT)
		for kwargs in (
			{"emails": ["a@b"]},
			{"emails": ["%"]},
			{"emails": None, "phones": ["555"]},
			{"emails": None, "phones": ["%"]},
		):
			with self.subTest(**kwargs), self.assertRaises(frappe.ValidationError):
				make_request(self.logger, **kwargs)
		self.assertEqual(frappe.db.count(DT), before)

	def test_a_blank_form_may_have_no_identifiers_yet(self):
		doc = doc_of(make_request(self.logger, emails=None, phones=None))
		self.assertEqual((len(doc.identifiers), len(doc.matches)), (0, 0))

	def test_blank_date_defaults_to_today_and_a_bad_channel_is_refused(self):
		doc = doc_of(make_request(self.logger, date_received=""))
		self.assertEqual(str(doc.date_received), frappe.utils.today())
		with self.assertRaises(frappe.ValidationError):
			make_request(self.logger, channel="Carrier pigeon")

	def test_the_number_follows_the_pdr_series(self):
		self.assertRegex(make_request(self.logger), r"^PDR-\d{4}$")

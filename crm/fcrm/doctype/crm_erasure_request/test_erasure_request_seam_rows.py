# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""What the match and identifier seams accept: registry doctypes, real records, server normalization"""

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	REP,
	as_user,
	ensure_users,
	make_contact,
	make_deal,
	make_request,
)


class TestErasureRequestSeamRows(IntegrationTestCase):
	def setUp(self):
		ensure_users()
		self.contact = make_contact()
		with as_user(REP):
			self.request = make_request("Contact", self.contact.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def stored_matches(self):
		return frappe.get_all(
			"CRM Erasure Match", filters={"parent": self.request.name}, pluck="ref_name", order_by="idx"
		)

	def test_match_doctype_must_be_a_registry_match_source(self):
		"""N2: phase 03 acts on every match row, so only doctypes discovery can emit get in"""
		for ref_doctype, ref_name in (("User", "Administrator"), ("Version", "x"), ("DocType", "User")):
			with self.subTest(ref_doctype=ref_doctype), as_user(REP):
				self.request.reload()
				with self.assertRaises(frappe.ValidationError):
					self.request.replace_matches([{"ref_doctype": ref_doctype, "ref_name": ref_name}])
		self.assertEqual(self.stored_matches(), [])

	def test_match_record_must_exist(self):
		deal = make_deal()
		with as_user(REP):
			with self.assertRaises(frappe.ValidationError):
				self.request.replace_matches([{"ref_doctype": "CRM Deal", "ref_name": "CRM-DEAL-NOPE"}])
			self.request.reload()
			self.request.replace_matches([{"ref_doctype": "CRM Deal", "ref_name": deal.name}])
		self.assertEqual(self.stored_matches(), [deal.name])

	def test_stored_match_of_a_vanished_record_survives_a_refresh(self):
		"""Rows already on the request were checked when added; a refresh must not trip on them"""
		deal = make_deal()
		with as_user(REP):
			self.request.replace_matches([{"ref_doctype": "CRM Deal", "ref_name": deal.name}])
		frappe.db.delete("CRM Deal", {"name": deal.name})
		with as_user(REP):
			self.request.reload()
			self.request.replace_matches([{"ref_doctype": "CRM Deal", "ref_name": deal.name, "excluded": 1}])
		self.assertEqual(self.stored_matches(), [deal.name])

	def test_identifiers_are_normalized_by_the_server(self):
		"""N3: a caller-sent `normalized` never reaches the database"""
		rows = [
			{"kind": "Email", "value": "Dana@Example.com", "normalized": "victim@x.com"},
			{"kind": "Phone", "value": "+1 415-555-0177", "normalized": "+19999999999"},
		]
		frappe.db.set_value("Contact", self.contact.name, "email_id", "dana@example.com")  # on the source
		with as_user(REP):
			self.request.set_identifiers(rows)
		self.request.reload()
		self.assertEqual(
			[(r.kind, r.value, r.normalized) for r in self.request.identifiers],
			[("Email", "Dana@Example.com", "dana@example.com"), ("Phone", "+1 415-555-0177", "+14155550177")],
		)

	def test_invalid_identifier_names_its_position_not_its_value(self):
		rows = [
			{"kind": "Email", "value": "dana@example.com"},
			{"kind": "Email", "value": "secret-not-an-email"},
		]
		with as_user(REP), self.assertRaises(frappe.ValidationError) as ctx:
			self.request.set_identifiers(rows)
		self.assertIn("Email 2", str(ctx.exception))
		self.assertNotIn("secret-not-an-email", str(ctx.exception))

	def test_phone_region_is_the_callers_choice_but_normalization_is_not(self):
		"""Numbers typed without a country code parse in `region` (site default when omitted)"""
		rows = [{"kind": "Phone", "value": "(415) 555-0123", "normalized": "+19999999999"}]
		frappe.db.set_value("Contact", self.contact.name, "phone", "+1 415 555 0123")  # on the source
		with as_user(REP):
			self.request.set_identifiers(rows, region="US")
		self.request.reload()
		self.assertEqual(self.request.identifiers[0].normalized, "+14155550123")

# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The do-not-contact list: hashed entries, lookups, the secret health check (design 5.9)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy import do_not_contact
from crm.privacy.do_not_contact import (
	add_entries,
	blocked_values,
	has_entries,
	is_blocked,
	secret_available,
)
from crm.privacy.install import setup
from crm.privacy.tests.make_test_user import forget_dnc_secret

DNC = "CRM Do Not Contact"
EMAIL, PHONE = "marisol.vega@example.net", "+15305550123"


class TestDoNotContact(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()

	def tearDown(self):
		frappe.db.rollback()

	def test_entries_hold_only_a_hash(self):
		self.assertEqual(add_entries([("email", EMAIL), ("phone", PHONE)]), 2)

		rows = frappe.get_all(DNC, fields=["kind", "identifier_hash", "created_on"])
		self.assertEqual(sorted(r.kind for r in rows), ["Email", "Phone"])
		self.assertEqual(rows[0].created_on, frappe.utils.getdate())
		dump = frappe.as_json(frappe.get_all(DNC, fields=["*"])).lower()
		for plain in ("marisol", "example.net", "5305550123"):
			self.assertNotIn(plain, dump)
		self.assertEqual({len(r.identifier_hash) for r in rows}, {64})

	def test_the_same_person_in_another_format_is_one_entry(self):
		self.assertEqual(add_entries([("email", EMAIL), ("Email", "  Marisol.Vega@Example.NET ")]), 1)
		self.assertEqual(add_entries([("phone", "(530) 555-0123"), ("phone", PHONE)]), 1)
		self.assertEqual(add_entries([("email", EMAIL)]), 0)
		self.assertEqual(frappe.db.count(DNC), 2)

	def test_an_empty_value_is_skipped_and_an_unknown_kind_refused(self):
		self.assertEqual(add_entries([("email", "  "), ("phone", None), ("phone", "abc")]), 0)
		self.assertEqual(frappe.db.count(DNC), 0)
		with self.assertRaises(ValueError):
			add_entries([("fax", "123")])

	def test_lookup_returns_only_the_blocked_pairs(self):
		add_entries([("email", EMAIL), ("phone", PHONE)])
		values = [("email", " MARISOL.vega@example.net"), ("phone", "530-555-0123"), ("email", "ok@example.net")]

		self.assertEqual(blocked_values(values), values[:2])
		self.assertTrue(is_blocked("phone", "(530) 555-0123"))
		self.assertFalse(is_blocked("email", "ok@example.net"))

	def test_an_email_and_a_phone_with_the_same_text_do_not_collide(self):
		add_entries([("email", "5305550123")])
		self.assertFalse(is_blocked("phone", "5305550123"))

	def test_nothing_to_check_needs_no_secret(self):
		forget_dnc_secret()
		self.assertFalse(has_entries())
		self.assertEqual(blocked_values([("email", EMAIL), ("email", "")]), [])
		self.assertEqual(blocked_values([]), [])

	def test_secret_health_check(self):
		self.assertTrue(secret_available())
		add_entries([("email", EMAIL)])
		self.assertTrue(secret_available())

		forget_dnc_secret()

		self.assertFalse(secret_available())

	def test_the_row_is_named_by_its_hash(self):
		add_entries([("email", EMAIL)])

		(row,) = frappe.get_all(DNC, fields=["name", "identifier_hash"])

		self.assertEqual(row.name, row.identifier_hash)

	def test_adding_the_same_identifier_twice_in_one_call_leaves_one_row(self):
		self.assertEqual(add_entries([("email", EMAIL), ("email", EMAIL.upper())]), 1)
		self.assertEqual(frappe.db.count(DNC), 1)

	def test_a_racing_duplicate_is_ignored_not_raised(self):
		"""Another job committed the same hash after this one looked: the insert meets the primary key."""
		add_entries([("email", EMAIL)])

		with patch.object(do_not_contact, "_listed", return_value=False):
			add_entries([("email", EMAIL), ("phone", PHONE)])  # must not raise or roll anything back

		self.assertEqual(frappe.db.count(DNC), 2)
		self.assertTrue(is_blocked("phone", PHONE))

	def test_an_international_prefix_is_the_same_identifier(self):
		add_entries([("phone", "+1 415 555 0199")])

		self.assertTrue(is_blocked("phone", "001 415 555 0199"))
		self.assertEqual(add_entries([("phone", "001 415 555 0199")]), 0)

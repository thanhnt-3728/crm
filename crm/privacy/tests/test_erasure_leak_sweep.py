# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Anti-goal of design 2: personal data quietly survives somewhere the CRM controls.

After the erasure, and again after the close, every text-like column of every table in the database is searched for
her emails, her phones (in several layouts) and her full name. Expected hits: none, except the request's own rows
until it is closed, and `CRM Retained Contract.person_name` when a signed-contract reference was given (design
5.11). Her files must be gone from the disk, and the do-not-contact table must hold no plaintext.
"""

import os
import re

import frappe

from crm.api.erasure_review import set_contract_references
from crm.privacy.tests.erasure_fixture import EMAIL, EMAIL2, PHONE, PHONE2
from crm.privacy.tests.erasure_lifecycle_case import LifecycleCase
from crm.privacy.tests.leak_sweep_scan import email_pattern, name_pattern, phone_pattern, scan, text_columns
from crm.privacy.tests.make_test_user import as_user

PATTERNS = {
	"email": email_pattern(EMAIL),
	"email 2": email_pattern(EMAIL2),
	"phone": phone_pattern(PHONE),
	"phone 2": phone_pattern(PHONE2),
	"full name": name_pattern("Marisol", "Vega"),
}
RETAINED = ("tabCRM Retained Contract", "person_name")
# File names the fixture attaches to her records (erased) and to the deal she was removed from (kept).
HER_FILES = ("marisol", "lead-card", "proposal-for-marisol", "proposal-email", "voice-marisol")
KEPT_FILE = "price-list"
HASH = re.compile(r"^[0-9a-f]{32,}$")


def files_on_disk(*stems: str) -> list[str]:
	"""Files of the site (public and private) whose name starts with one of `stems`."""
	found = []
	for folder in ("public", "private"):
		base = frappe.get_site_path(folder, "files")
		found += [f for f in os.listdir(base) if f.lower().startswith(stems)] if os.path.isdir(base) else []
	return found


class SweepCase(LifecycleCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 36)
		self.known = {"__global_search": self.old_search_rows}  # rows earlier test runs left in MyISAM

	def sweep(self) -> dict:
		return scan(PATTERNS, self.known)

	def assertDoNotContactHoldsOnlyHashes(self):
		"""Every row is a keyed hash; the sweep of the same test finds none of her values in the table."""
		rows = frappe.get_all("CRM Do Not Contact", fields=["name", "kind", "identifier_hash"])
		self.assertGreaterEqual(len(rows), 4)  # two emails and two phones were blocked
		for row in rows:
			self.assertRegex(row.identifier_hash, HASH)
			self.assertEqual(row.name, row.identifier_hash)


class TestSweepSeesHerBeforeErasure(SweepCase):
	"""A sweep that finds nothing proves nothing: first it must find her in the fixture, across many tables."""

	def test_the_sweep_finds_her_everywhere_and_the_lookalikes_are_not_her(self):
		hits = self.sweep()
		tables = {table for table, _column in hits}
		for table in ("tabCRM Lead", "tabCRM Deal", "tabContact", "tabCommunication", "tabVersion",
				"tabDeleted Document", "tabCRM Call Log", "tabWA Message", "__global_search"):  # fmt: skip
			self.assertIn(table, tables)
		self.assertGreater(len(tables), 30)
		self.assertGreater(len(text_columns()), 300)  # it really looks at (nearly) the whole schema
		self.assertEqual(hits[("tabCRM Lead", "email")], {"email": 1})  # Adam Vega's lead is not hers
		self.assertEqual(hits[("tabCRM Lead", "mobile_no")], {"phone": 1})
		for stem in HER_FILES:
			self.assertTrue(files_on_disk(stem), stem)


class TestNothingSurvives(SweepCase):
	def test_after_the_erasure_only_the_request_and_the_retained_contract_hold_her(self):
		as_user(self.compliance, set_contract_references, self.request, ["CT-1001"])
		self.approve_and_run()
		self.assertEqual(self.stored("status").status, "Erased")

		hits = self.sweep()
		leaked = {k: v for k, v in hits.items() if not k[0].startswith("tabCRM Erasure ") and k != RETAINED}
		self.assertEqual(leaked, {})
		self.assertEqual(hits[RETAINED], {"full name": 1})  # her name and nothing else (design 5.11)
		self.assertFalse(files_on_disk(*HER_FILES))
		self.assertTrue(files_on_disk(KEPT_FILE))  # the deal she was removed from keeps its files
		self.assertDoNotContactHoldsOnlyHashes()

	def test_after_the_close_only_the_retained_contract_holds_her(self):
		as_user(self.compliance, set_contract_references, self.request, ["CT-1001"])
		self.approve_and_run()
		self.close_and_finish()
		self.assertEqual(self.stored("status").status, "Closed")

		self.assertEqual(self.sweep(), {RETAINED: {"full name": 1}})
		self.assertFalse(files_on_disk(*HER_FILES))
		self.assertDoNotContactHoldsOnlyHashes()

	def test_after_the_close_without_a_contract_nothing_holds_her_at_all(self):
		self.approve_and_run()
		self.close_and_finish()

		self.assertEqual(self.sweep(), {})
		self.assertFalse(files_on_disk(*HER_FILES))
		self.assertFalse(frappe.db.count("CRM Retained Contract", {"request": self.request}))
		self.assertDoNotContactHoldsOnlyHashes()

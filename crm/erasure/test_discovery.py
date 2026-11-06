# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from collections import defaultdict
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.erasure.discovery import discover
from crm.erasure.erasure_test_fixtures import (
	HER_EMAILS,
	HER_IMAGE_URL,
	build_marisol,
	cleanup_marisol,
	log_marisol_request,
)
from crm.erasure.registry import REGISTRY, registry_position
from crm.erasure.shared_files import file_url_is_shared
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP, as_user

MATCHABLE = {e.doctype for e in REGISTRY if e.match_rows and e.kind != "hidden"}
HIDDEN = {e.doctype for e in REGISTRY if e.kind == "hidden" and e.finders}


def by_doctype(matches) -> dict[str, set[str]]:
	found = defaultdict(set)
	for row in matches:
		found[row["ref_doctype"]].add(row["ref_name"])
	return found


class TestDiscovery(IntegrationTestCase):
	"""Discovery only reads, so the fixture is built once per class and rolled back after it"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fx = build_marisol()
		cls.request = log_marisol_request(cls.fx)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		cleanup_marisol()
		super().tearDownClass()

	def row(self, result, label):
		name = self.fx.names[label]
		return next(r for r in result.matches if r["ref_name"] == name)

	def test_finds_every_source(self):
		result = discover(self.request)
		found = by_doctype(result.matches)
		for doctype in sorted(MATCHABLE):
			with self.subTest(doctype=doctype):
				self.assertEqual(found.get(doctype, set()), self.fx.expected.get(doctype, set()))
		self.assertEqual(set(found) - MATCHABLE, set())
		# every source has something seeded, so a registry row dropped from discovery fails here
		self.assertEqual({d for d in MATCHABLE if self.fx.expected.get(d)}, MATCHABLE)

	def test_hidden_copies_are_counted_not_listed(self):
		result = discover(self.request)
		self.assertFalse({r["ref_doctype"] for r in result.matches} & HIDDEN)
		for doctype in sorted(HIDDEN - {"__global_search"}):
			with self.subTest(doctype=doctype):
				self.assertEqual(result.hidden[doctype], len(self.fx.hidden[doctype]))
				self.assertGreater(result.hidden[doctype], 0)

	def test_global_search_rows_are_counted(self):
		# __global_search is MyISAM: rollback does not undo it, so clean up explicitly
		rows = [
			("CRM Lead", self.fx.lead, "Lead"),
			("Note", "gs-erasure-1", f"mail {HER_EMAILS[0]}"),
			("Note", "gs-erasure-2", "mail jomarisol.reyes@example.net"),
		]
		try:
			for doctype, name, content in rows:
				frappe.db.sql(
					"insert into `__global_search` (doctype, name, title, content, route, published) "
					"values (%s, %s, %s, %s, '', 0)",
					(doctype, name, name, content),
				)
			self.assertEqual(discover(self.request).hidden["__global_search"], 2)
		finally:
			frappe.db.sql("delete from `__global_search` where name in %s", ([r[1] for r in rows],))

	def test_reasons_actions_order_and_no_duplicates(self):
		result = discover(self.request)
		keys = [(r["ref_doctype"], r["ref_name"]) for r in result.matches]
		self.assertEqual(len(keys), len(set(keys)))
		positions = [registry_position(r["ref_doctype"]) for r in result.matches]
		self.assertEqual(positions, sorted(positions))
		expect = {
			"lead": ("linked", "scrub"),
			"deal_open": ("linked", "scrub"),
			"comm_on_lead": ("activity", "replace_content"),
			"comm_from_her": ("email", "replace_content"),
			"comm_cc_on_colleague_deal": ("email", "replace_content"),
			"comm_sms": ("phone", "replace_content"),
			"wa_from_her_number": ("phone", "replace_content"),
			"address_hers": ("linked", "scrub"),
			"address_shared": ("linked", "unlink"),
			"file_on_lead": ("linked", "delete_permanently"),
			"comment_by_her": ("email", "replace_content"),
		}
		for label, (reason, action) in expect.items():
			with self.subTest(label=label):
				row = self.row(result, label)
				self.assertEqual((row["reason"], row["action"]), (reason, action))
		self.assertEqual(set(result.matches[0]), {"ref_doctype", "ref_name", "reason", "action"})

	def test_near_misses(self):
		result = discover(self.request)
		found = {(r["ref_doctype"], r["ref_name"]) for r in result.matches}
		for doctype, names in self.fx.near_misses.items():
			for name in names:
				with self.subTest(doctype=doctype, name=name):
					self.assertNotIn((doctype, name), found)

	def test_secondary_contact_deal(self):
		found = by_doctype(discover(self.request).matches)
		self.assertNotIn(self.fx.colleague_deal, found["CRM Deal"])
		self.assertIn(self.fx.names["colleague_deal_row_her"], found["CRM Contacts"])
		self.assertNotIn(self.fx.names["colleague_deal_row_kai"], found["CRM Contacts"])
		self.assertNotIn(self.fx.colleague_contact, found["Contact"])
		self.assertNotIn(self.fx.names["comment_on_colleague_deal"], found["Comment"])

	def test_contact_source_reaches_her_lead_and_deals_through_links(self):
		request = log_marisol_request(
			self.fx, source=("Contact", self.fx.contact), emails=(), phones=("+1 415 555 0177",)
		)
		found = by_doctype(discover(request).matches)
		self.assertEqual(found["CRM Deal"], {self.fx.deal_won, self.fx.deal_open})
		self.assertEqual(found["CRM Lead"], {self.fx.lead})
		self.assertNotIn(self.fx.names["comm_from_her"], found["Communication"])  # needs her email
		self.assertIn(self.fx.names["comm_on_lead"], found["Communication"])

	def test_discovery_only_reads(self):
		real_sql = frappe.db.sql
		statements = []

		def spy(query, *args, **kwargs):
			statements.append(str(query).lstrip().split(None, 1)[0].lower())
			return real_sql(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", side_effect=spy):
			discover(self.request)
		self.assertTrue(statements)
		self.assertEqual(set(statements) - {"select", "with", "show", "("}, set())

	def test_excluded_matches_are_not_traversed(self):
		request = log_marisol_request(self.fx)
		excluded = {self.fx.names["comm_from_her"], self.fx.names["comm_on_lead"]}
		rows = [{**r, "excluded": int(r["ref_name"] in excluded)} for r in discover(request).matches]
		with as_user(REP):
			request.replace_matches(rows)
		result = discover(request)
		found = by_doctype(result.matches)
		self.assertTrue(excluded <= found["Communication"])  # still listed, so the rep sees them
		self.assertNotIn(self.fx.names["comment_on_comm"], found["Comment"])  # only via the thread
		self.assertIn(self.fx.names["comment_on_comm_by_her"], found["Comment"])  # her comment_email
		self.assertNotIn(self.fx.names["file_on_email"], found["File"])
		self.assertEqual(result.hidden["Email Queue"], len(self.fx.hidden["Email Queue"]) - 1)

	def test_shared_file_content_is_detected(self):
		hers = {self.fx.names["file_contact_image"], self.fx.names["file_on_lead"]}
		self.assertTrue(file_url_is_shared(HER_IMAGE_URL, hers))
		self.assertFalse(file_url_is_shared("/private/files/file_on_lead.txt", hers))

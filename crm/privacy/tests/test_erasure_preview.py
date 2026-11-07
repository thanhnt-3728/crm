# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The approval screen's preview (phase 05 step 4; design 5.6 "The approval screen")."""

import frappe
from frappe.tests import UnitTestCase

from crm.api.erasure_review import get_erasure_preview, set_contract_references
from crm.privacy.erasure.plan import KINDS
from crm.privacy.erasure.preview_kinds import KIND_INFO
from crm.privacy.tests.erasure_fixture import ErasureTestCase
from crm.privacy.tests.make_test_user import as_user, force_request, make_contact, make_user

TWILIO = "Delete recordings at provider (Twilio)"


class PreviewCase(ErasureTestCase):
	def preview(self):
		return as_user(self.compliance, get_erasure_preview, self.request)

	def removing(self):
		return {entry["kind"]: entry for entry in self.preview()["remove"]}


class TestWhoMaySee(PreviewCase):
	def test_only_compliance_with_an_explicit_role(self):
		manager2 = make_user("pdr.manager2@example.com", roles=["Sales Manager"])
		for user in (self.other, self.manager, manager2, "Administrator"):
			with self.assertRaises(frappe.PermissionError, msg=user):
				as_user(user, get_erasure_preview, self.request)

	def test_a_finished_request_has_nothing_left_to_preview(self):
		for status in ("Erased", "Declined", "Closed"):
			force_request(self.request, status=status)
			with self.assertRaises(frappe.ValidationError, msg=status):
				self.preview()


class TestKinds(UnitTestCase):
	def test_every_kind_of_the_plan_has_a_label_and_a_doctype(self):
		self.assertEqual(set(KIND_INFO), set(KINDS))


class TestRemove(PreviewCase):
	def test_counts_per_kind_match_the_scenario(self):
		counts = {kind: entry["count"] for kind, entry in self.removing().items()}
		expected = {
			"leads": 1,
			"contacts": 1,
			"addresses": 1,
			"deals_on": 1,
			"deals_copy": 1,
			"deals_removed": 1,
			"communications": 6,
			"call_logs": 3,
			"notes": 4,
			"tasks": 3,
			"files": 5,
			"wa_messages": 1,
			"wa_profiles": 1,
			"event_participants": 1,
			"failed_sync_logs": 1,
			"hold_notifications": 2,
		}
		for kind, count in expected.items():
			self.assertEqual(counts.get(kind), count, kind)
		self.assertGreaterEqual(counts["comments"], 3)  # [I4]: every type
		self.assertGreaterEqual(counts["todos"], 3)
		self.assertGreaterEqual(counts["versions"], 3)
		self.assertGreaterEqual(counts["deleted_documents"], 1)

	def test_every_kind_has_a_label_and_links_to_its_records(self):
		leads = self.removing()["leads"]
		self.assertEqual(leads["label"], "Leads")
		self.assertEqual(
			leads["links"], [{"doctype": "CRM Lead", "name": self.p.lead, "label": "Marisol Vega"}]
		)

	def test_links_are_capped_but_the_count_is_not(self):
		entry = self.removing()["comments"]
		self.assertLessEqual(len(entry["links"]), 50)
		self.assertGreaterEqual(entry["count"], 3)

	def test_an_empty_kind_is_left_out(self):
		self.assertNotIn("unhandled_emails", self.removing())


class TestKeep(PreviewCase):
	def test_what_stays(self):
		keep = {item["kind"]: item for item in self.preview()["keep"]}
		for kind in ("organizations", "deal_values", "shells", "removed_deal_records"):
			self.assertIn(kind, keep)
		self.assertEqual(keep["shells"]["count"], 3)  # her lead and the two Won deals
		self.assertGreaterEqual(keep["removed_deal_records"]["count"], 4)
		self.assertNotIn("retained_contract", keep)

	def test_an_address_shared_with_a_colleague_is_kept_with_its_reason(self):
		links = [self.p.contact, self.p.colleague]
		frappe.get_doc(
			{"doctype": "Address", "address_title": "Sierra Office", "address_type": "Office",
			 "address_line1": "9 Main St", "city": "Chico", "country": "United States",
			 "links": [{"link_doctype": "Contact", "link_name": name} for name in links]}
		).insert(ignore_permissions=True)  # fmt: skip
		preview = self.preview()
		keep = {item["kind"]: item for item in preview["keep"]}
		self.assertEqual(keep["shared_addresses"]["count"], 1)
		self.assertIn("shared", keep["shared_addresses"]["text"].lower())
		self.assertNotIn("shared_addresses", [i["kind"] for i in preview["needs_attention"]])

	def test_a_contract_exception_is_listed_as_kept(self):
		as_user(self.compliance, set_contract_references, self.request, ["CT-1001"])
		keep = {item["kind"]: item for item in self.preview()["keep"]}
		self.assertEqual(keep["retained_contract"]["count"], 1)


class TestChecklistAndGaps(PreviewCase):
	def test_the_items_the_erasure_will_add_are_warned_about_before_they_exist(self):
		items = self.preview()["open_checklist"]
		self.assertEqual(items[0]["description"], TWILIO)
		self.assertRegex(
			items[1]["description"], r"^Check Data Import files for this person \(\d+ imports?\)$"
		)
		self.assertEqual(len(items), 2)
		self.assertTrue(all(i["predicted"] and i["auto"] for i in items))

	def test_an_item_compliance_added_is_listed_until_it_is_done(self):
		doc = frappe.get_doc("CRM Erasure Request", self.request)
		doc.append("checklist", {"description": "Ask the print shop"})
		doc.append("checklist", {"description": "Done already", "done": 1})
		from crm.privacy.request_status import server_write

		with server_write():
			doc.save(ignore_permissions=True)
		descriptions = {i["description"]: i for i in self.preview()["open_checklist"]}
		self.assertIn("Ask the print shop", descriptions)
		self.assertNotIn("Done already", descriptions)
		self.assertTrue(descriptions[TWILIO]["predicted"])
		self.assertFalse(descriptions["Ask the print shop"]["predicted"])

	def test_a_custom_field_off_the_list_is_a_gap(self):
		gaps = {(g["doctype"], g["fieldname"]): g for g in self.preview()["field_gaps"]}
		self.assertEqual(gaps[("CRM Lead", "personal_mobile")]["label"], "Personal mobile")
		self.assertNotIn(("CRM Lead", "email"), gaps)


class TestNeedsAttention(PreviewCase):
	def test_identifier_hits_are_counted_per_kept_identifier(self):
		hits = {h["identifier"]: h for h in self.preview()["identifier_hits"]}
		self.assertNotIn(self.p.shared_email, hits)  # excluded
		email = hits[self.p.email]
		self.assertEqual((email["records"], email["communications"], email["count"]), (4, 3, 7))
		self.assertEqual(hits[self.p.phone]["call_logs"], 2)
		self.assertEqual({h["outside_her_records"] for h in hits.values()}, {0})

	def test_a_record_the_mailbox_made_for_her_address_is_flagged(self):
		new = make_contact("Marisol", emails=[self.p.email], last_name="Vega Jr")
		preview = self.preview()
		hits = {h["identifier"]: h for h in preview["identifier_hits"]}
		self.assertEqual(hits[self.p.email]["outside_her_records"], 1)
		flagged = [i for i in preview["needs_attention"] if i["kind"] == "outside_records"]
		self.assertEqual(flagged[0]["count"], 1)
		self.assertNotIn(new, [link["name"] for link in self.removing()["contacts"]["links"]])

	def test_data_import_files_are_listed_for_a_manual_check(self):
		items = {i["kind"]: i for i in self.preview()["needs_attention"]}
		self.assertGreaterEqual(items["data_import"]["count"], 1)
		self.assertRegex(
			items["data_import"]["text"], r"Check Data Import files for this person \(\d+ imports?\)"
		)

	def test_open_deals_block_approval_and_are_named(self):
		frappe.db.set_value("CRM Deal", self.p.won, "status", "Negotiation")
		preview = self.preview()
		self.assertEqual(preview["blocked_by"], [{"doctype": "CRM Deal", "name": self.p.won}])

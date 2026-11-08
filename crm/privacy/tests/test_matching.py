import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_deal.test_crm_deal import create_test_contact
from crm.permissions.test_org_hierarchy import make_user
from crm.privacy.api import get_request, get_requests, log_request, refresh_request_matches, save_request
from crm.privacy.matching import identifier_usage, like_escape, refresh_matches
from crm.privacy.tests.factories import make_compliance_user, make_marisol, make_request


class TestMatching(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_log_from_lead_suggests_contact_and_both_deals(self):
		m = make_marisol()
		name = log_request("CRM Lead", m.lead)
		r = frappe.get_doc("CRM Erasure Request", name)
		self.assertEqual(r.requester_name, "Marisol Vega")
		confirmed = {(x.reference_doctype, x.reference_name) for x in r.matches if x.confirmed}
		self.assertEqual(confirmed, {("CRM Lead", m.lead)})
		suggested = {(x.reference_doctype, x.reference_name) for x in r.matches}
		self.assertTrue(
			{("Contact", m.contact), ("CRM Deal", m.open_deal), ("CRM Deal", m.won_deal)} <= suggested
		)

	def test_phone_in_other_format_matches(self):
		make_marisol()  # her records hold the same number in another format
		other = create_test_contact(first_name="Front", mobile_no="530.555.0142")
		r = make_request(identifiers=[{"kind": "Phone", "value": "+1 530 555 0142"}])
		refresh_matches(r)
		self.assertIn(("Contact", other.name), {(x.reference_doctype, x.reference_name) for x in r.matches})

	def test_excluded_identifier_does_not_match(self):
		make_marisol()  # records the excluded number would otherwise match
		r = make_request(identifiers=[{"kind": "Phone", "value": "5305550142", "excluded": 1}])
		refresh_matches(r)
		self.assertEqual(r.matches, [])

	def test_confirming_contact_pulls_its_identifiers(self):
		m = make_marisol()
		c = frappe.get_doc("Contact", m.contact)
		c.append("email_ids", {"email_id": "mv@home.example"})
		c.save()
		r = make_request(
			matches=[{"reference_doctype": "Contact", "reference_name": m.contact, "confirmed": 1}]
		)
		refresh_matches(r)
		self.assertIn(("Email", "mv@home.example"), {(i.kind, i.value) for i in r.identifiers})

	def test_summary_hides_details_after_submit(self):
		make_user("rep@example.com", ["Sales User"])
		frappe.set_user("rep@example.com")
		name = log_request()
		frappe.db.set_value("CRM Erasure Request", name, "status", "Awaiting Sign-off")
		out = get_request(name)
		self.assertEqual(set(out), {"access", "name", "status", "acknowledge_by", "respond_by", "days_left"})

	def test_save_request_rejects_unknown_keys(self):
		name = log_request()
		with self.assertRaises(frappe.ValidationError):
			save_request(name, {"status": "Erased"})

	def test_list_sorted_by_days_left(self):
		a = make_request(date_received=frappe.utils.add_days(frappe.utils.today(), -40)).name
		b = make_request(date_received=frappe.utils.today()).name
		names = [r["name"] for r in get_requests()]
		self.assertLess(names.index(a), names.index(b))

	def test_unrelated_records_are_not_suggested(self):
		make_marisol()
		stranger = create_test_contact(
			first_name="Stranger", email="stranger@example.com", mobile_no="2125550100"
		)
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"}])
		refresh_matches(r)
		self.assertNotIn(
			("Contact", stranger.name), {(x.reference_doctype, x.reference_name) for x in r.matches}
		)

	def test_refresh_drops_stale_unconfirmed_and_keeps_confirmed(self):
		m = make_marisol()
		stranger = create_test_contact(first_name="Stranger", email="stranger@example.com")
		stranger_confirmed = create_test_contact(first_name="Kept", email="kept@example.com")
		r = make_request(
			matches=[
				{"reference_doctype": "Contact", "reference_name": stranger.name, "confirmed": 0},
				{"reference_doctype": "Contact", "reference_name": stranger_confirmed.name, "confirmed": 1},
				{"reference_doctype": "Contact", "reference_name": m.contact, "confirmed": 1},
			]
		)
		refresh_matches(r)
		keys = {(x.reference_doctype, x.reference_name): x.confirmed for x in r.matches}
		self.assertNotIn(("Contact", stranger.name), keys)
		self.assertEqual(keys[("Contact", stranger_confirmed.name)], 1)
		self.assertEqual(keys[("Contact", m.contact)], 1)
		self.assertEqual(keys[("CRM Deal", m.open_deal)], 0)

	def test_like_wildcards_in_identifiers_match_literally(self):
		make_marisol()
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Hello",
				"sender": "marisol@sierrafoothills.example",
				"recipients": "sales@example.com",
				"content": "hi",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(like_escape("a%b_c\\d"), "a\\%b\\_c\\\\d")
		table = frappe.qb.DocType("Communication")
		for pattern in ("%", "_", "marisol_sierrafoothills.example"):
			hits = (
				frappe.qb.from_(table)
				.select(table.name)
				.where(table.sender.like(f"%{like_escape(pattern)}%"))
				.run()
			)
			self.assertEqual(len(hits), 0)
		r = make_request(identifiers=[{"kind": "Email", "value": "%"}, {"kind": "Email", "value": "_"}])
		self.assertEqual([u["emails"] for u in identifier_usage(r)], [0, 0])

	def test_identifier_usage_counts_records_emails_and_calls(self):
		m = make_marisol()
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Hello",
				"sender": "marisol@sierrafoothills.example",
				"recipients": "sales@example.com",
				"content": "hi",
				"reference_doctype": "CRM Lead",
				"reference_name": m.lead,
			}
		).insert(ignore_permissions=True)
		# a longer address that merely contains the identifier must not count
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Other",
				"sender": "x.marisol@sierrafoothills.example",
				"recipients": "sales@example.com",
				"content": "hi",
			}
		).insert(ignore_permissions=True)
		r = make_request(
			identifiers=[
				{"kind": "Email", "value": "Marisol@SierraFoothills.example"},
				{"kind": "Phone", "value": "(530) 555-0142"},
			]
		)
		usage = {u["kind"]: u for u in identifier_usage(r)}
		self.assertEqual(usage["Email"]["emails"], 1)
		self.assertGreaterEqual(usage["Email"]["records"], 3)  # lead, contact, and the deals
		self.assertEqual(usage["Phone"]["emails"], 0)
		self.assertEqual(usage["Phone"]["calls"], 0)
		for number, other in (("+1 530-555-0142", "+15125550100"), ("+15125550100", "+1 (530) 555 0142")):
			frappe.get_doc(
				{
					"doctype": "CRM Call Log",
					"id": frappe.generate_hash(length=10),
					"from": number,
					"to": other,
					"status": "Completed",
					"type": "Incoming",
				}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": frappe.generate_hash(length=10),
				"from": "+1 530-555-0199",
				"to": "+15125550100",
				"status": "Completed",
				"type": "Incoming",
			}
		).insert(ignore_permissions=True)
		usage = {u["kind"]: u for u in identifier_usage(r)}
		self.assertEqual(usage["Phone"]["calls"], 2)
		self.assertFalse(usage["Email"]["excluded"])


class TestRequestApi(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_log_requires_read_access_to_source(self):
		m = make_marisol(owner="Administrator")
		make_user("nobody@example.com", ["Sales User"])
		frappe.set_user("nobody@example.com")
		with self.assertRaises(frappe.PermissionError):
			log_request("CRM Lead", m.lead)

	def test_log_rejects_other_source_doctypes(self):
		with self.assertRaises(frappe.ValidationError):
			log_request("User", "Administrator")

	def test_log_from_deal_uses_primary_contact_name(self):
		m = make_marisol()
		name = log_request("CRM Deal", m.open_deal)
		r = frappe.get_doc("CRM Erasure Request", name)
		self.assertEqual(r.requester_name, "Marisol Vega")
		confirmed = {(x.reference_doctype, x.reference_name) for x in r.matches if x.confirmed}
		self.assertEqual(confirmed, {("CRM Deal", m.open_deal)})

	def test_logger_sees_full_while_logged_and_can_flags(self):
		make_user("rep2@example.com", ["Sales User"])
		frappe.set_user("rep2@example.com")
		name = log_request()
		out = get_request(name)
		self.assertEqual(out["access"], "full")
		self.assertEqual(
			out["can"],
			{
				"edit": True,
				"submit": True,
				"approve": False,
				"decline": False,
				"close": False,
				"manage_checklist": False,
			},
		)
		self.assertIn("doc", out)

	def test_other_user_cannot_read(self):
		make_user("rep3@example.com", ["Sales User"])
		make_user("rep4@example.com", ["Sales User"])
		frappe.set_user("rep3@example.com")
		name = log_request()
		frappe.set_user("rep4@example.com")
		with self.assertRaises(frappe.PermissionError):
			get_request(name)

	def test_approve_flag_excludes_logger(self):
		officer = make_compliance_user()
		frappe.set_user(officer)
		name = log_request()
		frappe.db.set_value("CRM Erasure Request", name, "status", "Awaiting Sign-off")
		self.assertFalse(get_request(name)["can"]["approve"])
		self.assertTrue(get_request(name)["can"]["decline"])
		other = make_compliance_user("other.officer@example.com")
		frappe.set_user(other)
		self.assertTrue(get_request(name)["can"]["approve"])

	def test_list_hides_names_for_summary_rows_and_other_users_rows(self):
		make_user("rep5@example.com", ["Sales User"])
		make_user("rep6@example.com", ["Sales User"])
		frappe.set_user("rep5@example.com")
		mine = log_request()
		frappe.set_user("rep6@example.com")
		theirs = log_request()
		frappe.db.set_value("CRM Erasure Request", theirs, "status", "Awaiting Sign-off")
		frappe.db.set_value("CRM Erasure Request", theirs, "requester_name", "Secret Name")
		frappe.set_user("rep5@example.com")
		rows = {r["name"]: r for r in get_requests()}
		self.assertIn(mine, rows)
		self.assertNotIn(theirs, rows)
		frappe.set_user("rep6@example.com")
		rows = {r["name"]: r for r in get_requests()}
		self.assertIsNone(rows[theirs]["requester_name"])

	def test_save_merges_tables_and_keeps_unmentioned_rows(self):
		m = make_marisol()
		name = log_request("CRM Lead", m.lead)
		doc = frappe.get_doc("CRM Erasure Request", name)
		count = len(doc.identifiers)
		first = doc.identifiers[0]
		out = save_request(
			name,
			{
				"requester_name": "M. Vega",
				"identifiers": [
					{"name": first.name, "excluded": 1},
					{"kind": "Email", "value": "New@Example.com"},
				],
			},
		)
		after = frappe.get_doc("CRM Erasure Request", name)
		self.assertEqual(len(after.identifiers), count + 1)
		self.assertEqual(after.identifiers[0].excluded, 1)
		self.assertEqual(after.identifiers[-1].value, "new@example.com")
		self.assertEqual(after.identifiers[-1].source, "Typed")
		self.assertEqual(out["doc"]["requester_name"], "M. Vega")

	def test_save_match_requires_read_access_to_record(self):
		m = make_marisol(owner="Administrator")
		make_user("rep7@example.com", ["Sales User"])
		frappe.set_user("rep7@example.com")
		name = log_request()
		with self.assertRaises(frappe.PermissionError):
			save_request(
				name,
				{"matches": [{"reference_doctype": "CRM Lead", "reference_name": m.lead, "confirmed": 1}]},
			)

	def test_logger_cannot_save_checklist_or_contract_references(self):
		make_user("rep8@example.com", ["Sales User"])
		frappe.set_user("rep8@example.com")
		name = log_request()
		with self.assertRaises(frappe.PermissionError):
			save_request(name, {"checklist": [{"description": "x"}]})
		with self.assertRaises(frappe.PermissionError):
			save_request(name, {"contract_references": "MSA-1"})
		with self.assertRaises(frappe.PermissionError):
			save_request(name, {"acknowledgment_sent": 1})

	def test_compliance_can_manage_checklist_and_refresh(self):
		officer = make_compliance_user()
		frappe.set_user(officer)
		name = log_request()
		out = save_request(
			name, {"checklist": [{"description": "Delete recordings"}], "contract_references": "MSA-1"}
		)
		row = out["doc"]["checklist"][0]
		self.assertEqual(row["description"], "Delete recordings")
		out = save_request(name, {"checklist": [{"name": row["name"], "done": 1}]})
		self.assertEqual(out["doc"]["checklist"][0]["done"], 1)
		self.assertEqual(out["doc"]["checklist"][0]["done_by"], officer)
		self.assertIn("doc", refresh_request_matches(name))

	def test_save_request_forbidden_after_submit_for_logger(self):
		make_user("rep9@example.com", ["Sales User"])
		frappe.set_user("rep9@example.com")
		name = log_request()
		frappe.db.set_value("CRM Erasure Request", name, "status", "Awaiting Sign-off")
		with self.assertRaises(frappe.PermissionError):
			save_request(name, {"requester_name": "x"})

	def test_compliance_ticks_checklist_and_acknowledges_on_erased_request(self):
		officer = make_compliance_user()
		frappe.set_user(officer)
		name = log_request()
		out = save_request(name, {"checklist": [{"description": "Delete recordings at provider (Twilio)"}]})
		row = out["doc"]["checklist"][0]
		frappe.db.set_value("CRM Erasure Request", name, "status", "Erased")
		self.assertFalse(get_request(name)["can"]["edit"])
		out = save_request(
			name,
			{
				"checklist": [{"name": row["name"], "done": 1}],
				"acknowledgment_sent": 1,
				"acknowledged_on": frappe.utils.today(),
			},
		)
		self.assertEqual(out["doc"]["checklist"][0]["done"], 1)
		self.assertEqual(out["doc"]["checklist"][0]["done_by"], officer)
		self.assertEqual(out["doc"]["acknowledgment_sent"], 1)
		# anything else still needs edit access
		with self.assertRaises(frappe.PermissionError):
			save_request(name, {"requester_name": "x"})

	def test_checklist_keys_skip_match_refresh(self):
		officer = make_compliance_user()
		m = make_marisol()
		name = log_request("CRM Lead", m.lead)
		frappe.set_user(officer)
		frappe.db.set_value("CRM Erasure Request", name, "status", "Erased")
		before = [(x["reference_doctype"], x["reference_name"]) for x in get_request(name)["doc"]["matches"]]
		# a new record matching the identifiers would be suggested by a refresh
		create_test_contact(first_name="Late", email="marisol@sierrafoothills.example")
		out = save_request(name, {"checklist": [{"description": "Delete recordings"}]})
		after = [(x["reference_doctype"], x["reference_name"]) for x in out["doc"]["matches"]]
		self.assertEqual(before, after)

	def test_logger_cannot_tick_checklist_or_acknowledge_on_logged_request(self):
		officer = make_compliance_user()
		frappe.set_user(officer)
		name = log_request()
		row = save_request(name, {"checklist": [{"description": "x"}]})["doc"]["checklist"][0]
		make_user("rep10@example.com", ["Sales User"])
		frappe.db.set_value("CRM Erasure Request", name, "logged_by", "rep10@example.com")
		frappe.set_user("rep10@example.com")
		with self.assertRaises(frappe.PermissionError):
			save_request(name, {"checklist": [{"name": row["name"], "done": 1}]})
		with self.assertRaises(frappe.PermissionError):
			save_request(name, {"acknowledgment_sent": 1})

	def test_manually_added_unconfirmed_match_survives_save(self):
		make_marisol()
		stranger = create_test_contact(first_name="Stranger", email="stranger@example.com")
		name = log_request()
		out = save_request(
			name,
			{"matches": [{"reference_doctype": "Contact", "reference_name": stranger.name, "confirmed": 0}]},
		)
		rows = {(x["reference_doctype"], x["reference_name"]): x for x in out["doc"]["matches"]}
		self.assertEqual(rows[("Contact", stranger.name)]["reason"], "Added manually")
		self.assertEqual(rows[("Contact", stranger.name)]["confirmed"], 0)
		out = save_request(name, {"requester_name": "S"})
		keys = {(x["reference_doctype"], x["reference_name"]) for x in out["doc"]["matches"]}
		self.assertIn(("Contact", stranger.name), keys)

	def test_non_dict_rows_are_validation_errors(self):
		name = log_request()
		for key in ("identifiers", "matches", "checklist"):
			with self.assertRaises(frappe.ValidationError):
				save_request(name, {key: ["not a dict"]})
		with self.assertRaises(frappe.ValidationError):
			save_request(name, {"identifiers": "nope"})

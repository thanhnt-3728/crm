# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, getdate, today

from crm.api.erasure import (
	approve,
	close,
	create_request,
	decline,
	get_request,
	list_requests,
	open_deals,
	preview,
	submit,
	update_matches,
)
from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import USERS, make_request, make_user
from crm.privacy import system_write
from crm.privacy.erasure import placeholder_content
from crm.privacy.setup import ensure_privacy_setup
from crm.tests.test_privacy_matching import OWNER, make_person
from crm.tests.test_privacy_preview import make_communication

SAVEPOINT = "test_privacy_api"
REQUEST = "CRM Erasure Request"
LOGGER = "rep@example.com"
COMPLIANCE = "comp1@example.com"
OTHER_COMPLIANCE = "comp2@example.com"
MANAGER = "salesmanager@example.com"
OTHER_REP = "otherrep@example.com"
RESTRICTED = {"name", "status", "received_on", "acknowledge_by", "respond_by", "days_left"}


@contextmanager
def approval_job_queued():
	"""Approving queues the erasure job; here nothing runs and nothing is committed."""
	with patch("crm.api.erasure.frappe.enqueue") as enqueue, patch("crm.api.erasure.frappe.db.commit"):
		yield enqueue


class TestPrivacyAPI(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		for email, roles in USERS.items():
			make_user(email, roles)
		make_user(OWNER, ["Sales User"])

	def setUp(self):
		frappe.db.savepoint(SAVEPOINT)
		frappe.db.set_single_value("System Settings", "country", "United States")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.privacy_system_write = False
		frappe.db.rollback(save_point=SAVEPOINT)

	def status_of(self, request):
		return frappe.db.get_value(REQUEST, request.name, "status")

	def awaiting(self, **values):
		"""A request the logger has submitted."""
		return make_request(status="Awaiting Sign-off", logged_by=LOGGER, **values)

	def erased(self, **values):
		return make_request(status="Erased", logged_by=LOGGER, **values)

	# -- create_request --------------------------------------------------------------------

	def test_create_request_from_lead_prefills_and_confirms(self):
		lead, contact, _deal = make_person("marisol@x.net", "+19165550100")
		frappe.set_user(LOGGER)
		name = create_request("Email", today(), start_doctype="CRM Lead", start_name=lead.name)

		request = frappe.get_doc(REQUEST, name)
		self.assertEqual(request.status, "Logged")
		self.assertEqual(request.logged_by, LOGGER)
		values = {(row.kind, row.value) for row in request.identifiers}
		self.assertIn(("Email", "marisol@x.net"), values)
		self.assertIn(("Phone", "+19165550100"), values)
		started = [row for row in request.matches if row.source == "Started from"]
		self.assertEqual(
			[(row.reference_doctype, row.reference_name) for row in started], [("CRM Lead", lead.name)]
		)
		self.assertTrue(started[0].confirmed)
		# The contact with the same email is suggested, not confirmed.
		suggested = {(row.reference_doctype, row.reference_name): row for row in request.matches}
		self.assertFalse(suggested[("Contact", contact.name)].confirmed)

	def test_create_request_from_contact_prefills_every_email_and_phone(self):
		_lead, contact, _deal = make_person("marisol@x.net", "+19165550100")
		contact = frappe.get_doc("Contact", contact.name)
		contact.append("email_ids", {"email_id": "m.vega@y.net"})
		contact.append("phone_nos", {"phone": "+14155550123"})
		contact.save(ignore_permissions=True)

		name = create_request("Phone", today(), start_doctype="Contact", start_name=contact.name)
		request = frappe.get_doc(REQUEST, name)
		values = {(row.kind, row.value.lower()) for row in request.identifiers}
		self.assertIn(("Email", "m.vega@y.net"), values)
		self.assertIn(("Phone", "+14155550123"), values)

	def test_create_request_deal_is_not_a_start_record(self):
		_lead, _contact, deal = make_person("marisol@x.net", "+19165550100")
		with self.assertRaises(frappe.ValidationError):
			create_request("Email", today(), start_doctype="CRM Deal", start_name=deal.name)

	def test_create_request_with_typed_identifiers(self):
		name = create_request(
			"Mail",
			today(),
			requester_names="Marisol Vega",
			identifiers=[
				{"kind": "Email", "value": " Marisol@X.net "},
				{"kind": "Email", "value": "marisol@x.net"},
			],
		)
		request = frappe.get_doc(REQUEST, name)
		self.assertEqual([(row.kind, row.value) for row in request.identifiers], [("Email", "Marisol@X.net")])
		self.assertEqual(request.requester_names, "Marisol Vega")

	def test_create_request_bad_identifier_kind(self):
		with self.assertRaises(frappe.ValidationError):
			create_request("Email", today(), identifiers=[{"kind": "Fax", "value": "123"}])

	# -- visibility ------------------------------------------------------------------------

	def test_logger_sees_full_request_while_logged(self):
		request = make_request(logged_by=LOGGER, requester_names="Marisol Vega")
		frappe.set_user(LOGGER)
		result = get_request(request.name)
		self.assertEqual(result["requester_names"], "Marisol Vega")
		self.assertIn("days_left", result)
		self.assertIn("day_number", result)

	def test_logger_sees_restricted_after_submit(self):
		request = self.awaiting(requester_names="Marisol Vega")
		frappe.set_user(LOGGER)
		result = get_request(request.name)
		self.assertEqual(set(result), RESTRICTED)
		self.assertEqual(result["days_left"], 45)

	def test_someone_else_cannot_see_request(self):
		request = make_request(logged_by=LOGGER)
		frappe.set_user(OTHER_REP)
		self.assertRaises(frappe.PermissionError, get_request, request.name)

	def test_compliance_and_sales_manager_see_everything(self):
		request = self.awaiting(requester_names="Marisol Vega")
		for user in (COMPLIANCE, MANAGER):
			frappe.set_user(user)
			result = get_request(request.name)
			self.assertEqual(result["requester_names"], "Marisol Vega")
			self.assertEqual(result["day_number"], 0)

	def test_list_sorted_by_days_left(self):
		late = make_request(received_on=add_days(today(), -30), logged_by=LOGGER)
		early = make_request(received_on=today(), logged_by=LOGGER)
		middle = make_request(received_on=add_days(today(), -10), logged_by=LOGGER)
		closed = make_request(status="Closed", logged_by=LOGGER)
		frappe.set_user(COMPLIANCE)
		names = [
			row["name"]
			for row in list_requests()
			if row["name"] in {r.name for r in (late, early, middle, closed)}
		]
		self.assertEqual(names, [late.name, middle.name, early.name])
		with_closed = [row["name"] for row in list_requests(include_closed=1)]
		self.assertIn(closed.name, with_closed)

	def test_list_for_logger_is_restricted_after_submit_and_hides_others(self):
		logged = make_request(logged_by=LOGGER)
		submitted = self.awaiting()
		theirs = make_request(logged_by=OTHER_REP)
		frappe.set_user(LOGGER)
		rows = {row["name"]: row for row in list_requests()}
		self.assertNotIn(theirs.name, rows)
		self.assertIn("channel", rows[logged.name])
		self.assertEqual(set(rows[submitted.name]), RESTRICTED)

	# -- update_matches and submit ---------------------------------------------------------

	def match_list(self, lead, confirmed=1):
		return [{"reference_doctype": "CRM Lead", "reference_name": lead.name, "confirmed": confirmed}]

	def test_logger_updates_matches_while_logged(self):
		lead, _contact, _deal = make_person("marisol@x.net", "+19165550100")
		request = make_request(logged_by=LOGGER)
		frappe.set_user(LOGGER)
		update_matches(
			request.name, self.match_list(lead), [{"kind": "Email", "value": "marisol@x.net", "excluded": 0}]
		)
		request.reload()
		self.assertEqual([(m.reference_name, m.confirmed) for m in request.matches], [(lead.name, 1)])
		by_value = {row.value: row for row in request.identifiers}
		# Her phone came in from the confirmed lead, and the email was counted.
		self.assertIn("+19165550100", by_value)
		self.assertGreaterEqual(by_value["marisol@x.net"].match_count, 1)

	def test_update_matches_keeps_excluded_identifier(self):
		request = make_request(logged_by=LOGGER, identifiers=[{"kind": "Email", "value": "office@x.net"}])
		frappe.set_user(LOGGER)
		update_matches(request.name, [], [{"kind": "Email", "value": "office@x.net", "excluded": 1}])
		request.reload()
		self.assertEqual([(row.value, row.excluded) for row in request.identifiers], [("office@x.net", 1)])

	def test_update_matches_rejects_unknown_record(self):
		request = make_request(logged_by=LOGGER)
		frappe.set_user(LOGGER)
		bad = [{"reference_doctype": "CRM Lead", "reference_name": "no-such-lead", "confirmed": 1}]
		self.assertRaises(frappe.ValidationError, update_matches, request.name, bad, [])

	def test_logger_cannot_update_matches_after_submit(self):
		request = self.awaiting()
		frappe.set_user(LOGGER)
		self.assertRaises(frappe.PermissionError, update_matches, request.name, [], [])

	def test_compliance_updates_matches_before_approval(self):
		lead, _contact, _deal = make_person("marisol@x.net", "+19165550100")
		request = self.awaiting()
		frappe.set_user(COMPLIANCE)
		update_matches(request.name, self.match_list(lead), [])
		request.reload()
		self.assertEqual(len(request.matches), 1)

	def test_sales_manager_cannot_update_matches(self):
		request = make_request(logged_by=LOGGER)
		frappe.set_user(MANAGER)
		self.assertRaises(frappe.PermissionError, update_matches, request.name, [], [])

	def test_submit_moves_to_awaiting_sign_off(self):
		lead, _contact, _deal = make_person("marisol@x.net", "+19165550100", status="Won")
		request = make_request(logged_by=LOGGER)
		frappe.set_user(LOGGER)
		update_matches(request.name, self.match_list(lead), [])
		self.assertEqual(submit(request.name), "Awaiting Sign-off")
		self.assertEqual(self.status_of(request), "Awaiting Sign-off")

	def test_preview_is_compliance_only(self):
		request = self.awaiting()
		frappe.set_user(MANAGER)
		self.assertRaises(frappe.PermissionError, preview, request.name)
		frappe.set_user(COMPLIANCE)
		self.assertIn("remove", preview(request.name))

	# -- approve ---------------------------------------------------------------------------

	def test_approve_requires_typed_number(self):
		request = self.awaiting()
		frappe.set_user(COMPLIANCE)
		with approval_job_queued() as enqueue:
			self.assertRaises(frappe.ValidationError, approve, request.name, "pdr-0001")
		enqueue.assert_not_called()
		self.assertEqual(self.status_of(request), "Awaiting Sign-off")

	def test_logger_cannot_approve(self):
		request = self.awaiting()
		frappe.set_user(LOGGER)
		self.assertRaises(frappe.PermissionError, approve, request.name, request.name)

	def test_compliance_logger_cannot_approve_own_request(self):
		request = make_request(status="Awaiting Sign-off", logged_by=COMPLIANCE)
		frappe.set_user(COMPLIANCE)
		self.assertRaises(frappe.PermissionError, approve, request.name, request.name)

	def test_sales_manager_cannot_approve(self):
		request = self.awaiting()
		frappe.set_user(MANAGER)
		self.assertRaises(frappe.PermissionError, approve, request.name, request.name)

	def test_approve_sets_erasing_and_queues_one_job(self):
		request = self.awaiting()
		frappe.set_user(COMPLIANCE)
		with approval_job_queued() as enqueue:
			approve(request.name, request.name)
		request.reload()
		self.assertEqual((request.status, request.approved_by), ("Erasing", COMPLIANCE))
		self.assertTrue(request.approved_on)
		enqueue.assert_called_once_with(
			"crm.privacy.erasure.run_erasure",
			request_name=request.name,
			queue="long",
			enqueue_after_commit=True,
		)

	def test_approve_bumps_modified(self):
		request = self.awaiting()
		before = frappe.db.get_value(REQUEST, request.name, ["modified", "modified_by"], as_dict=True)
		frappe.set_user(COMPLIANCE)
		with approval_job_queued():
			approve(request.name, request.name)
		after = frappe.db.get_value(REQUEST, request.name, ["modified", "modified_by"], as_dict=True)
		self.assertNotEqual(after.modified, before.modified)
		self.assertEqual(after.modified_by, COMPLIANCE)

	def test_stale_copy_cannot_undo_an_approval(self):
		"""A copy loaded before the approval can neither be saved over it nor edit matches."""
		request = self.awaiting()
		stale = frappe.get_doc(REQUEST, request.name)
		frappe.set_user(COMPLIANCE)
		with approval_job_queued():
			approve(request.name, request.name)

		with self.assertRaises(frappe.TimestampMismatchError), system_write():
			stale.save(ignore_permissions=True)
		self.assertRaises(frappe.PermissionError, update_matches, request.name, [], [])
		self.assertRaises(frappe.PermissionError, submit, request.name)
		self.assertEqual(self.status_of(request), "Erasing")

	def test_double_approve_second_fails(self):
		request = self.awaiting()
		with approval_job_queued() as enqueue:
			frappe.set_user(COMPLIANCE)
			approve(request.name, request.name)
			frappe.set_user(OTHER_COMPLIANCE)
			self.assertRaises(frappe.ValidationError, approve, request.name, request.name)
		self.assertEqual(enqueue.call_count, 1)
		self.assertEqual(frappe.db.get_value(REQUEST, request.name, "approved_by"), COMPLIANCE)

	def test_approve_not_possible_while_on_hold_or_logged(self):
		for status in ("On Hold", "Logged"):
			request = make_request(status=status, logged_by=LOGGER)
			frappe.set_user(COMPLIANCE)
			with approval_job_queued() as enqueue:
				self.assertRaises(frappe.ValidationError, approve, request.name, request.name)
			enqueue.assert_not_called()
			frappe.set_user("Administrator")

	def test_approve_rechecks_open_deals_and_puts_on_hold(self):
		_lead, contact, _deal = make_person("marisol@x.net", "+19165550100", status="Open")
		request = self.awaiting(
			matches=[{"reference_doctype": "Contact", "reference_name": contact.name, "confirmed": 1}]
		)
		frappe.set_user(COMPLIANCE)
		with approval_job_queued() as enqueue:
			self.assertRaises(frappe.ValidationError, approve, request.name, request.name)
		enqueue.assert_not_called()
		self.assertEqual(self.status_of(request), "On Hold")

	def test_approve_recheck_notifies_deal_owners(self):
		_lead, contact, deal = make_person("marisol@x.net", "+19165550100", status="Open")
		request = self.awaiting(
			matches=[{"reference_doctype": "Contact", "reference_name": contact.name, "confirmed": 1}]
		)
		frappe.set_user(COMPLIANCE)
		with approval_job_queued():
			self.assertRaises(frappe.ValidationError, approve, request.name, request.name)
		text = frappe.db.get_value(
			"CRM Notification",
			{"to_user": deal.deal_owner, "type": "Privacy", "reference_name": deal.name},
			"notification_text",
		)
		self.assertTrue(text)
		self.assertIn(request.name, text)

	def test_open_deals_lists_the_deals_holding_the_request(self):
		_lead, contact, deal = make_person("marisol@x.net", "+19165550100", status="Open")
		request = make_request(
			status="On Hold",
			logged_by=LOGGER,
			matches=[{"reference_doctype": "Contact", "reference_name": contact.name, "confirmed": 1}],
		)
		frappe.set_user(COMPLIANCE)
		self.assertEqual(open_deals(request.name), [deal.name])
		frappe.set_user(MANAGER)
		self.assertEqual(open_deals(request.name), [deal.name])

	def test_open_deals_refused_for_the_logger(self):
		request = make_request(status="On Hold", logged_by=LOGGER)
		frappe.set_user(LOGGER)
		self.assertRaises(frappe.PermissionError, open_deals, request.name)

	# -- decline ---------------------------------------------------------------------------

	def test_decline_needs_reason(self):
		request = self.awaiting()
		frappe.set_user(COMPLIANCE)
		self.assertRaises(frappe.ValidationError, decline, request.name, "  ")
		self.assertEqual(self.status_of(request), "Awaiting Sign-off")

	def test_decline_sets_status_and_reason(self):
		request = self.awaiting()
		frappe.set_user(COMPLIANCE)
		decline(request.name, "Identity not verifiable")
		request.reload()
		self.assertEqual((request.status, request.denial_reason), ("Declined", "Identity not verifiable"))

	def test_logger_and_manager_cannot_decline(self):
		request = self.awaiting()
		for user in (LOGGER, MANAGER):
			frappe.set_user(user)
			self.assertRaises(frappe.PermissionError, decline, request.name, "No")

	def test_compliance_logger_cannot_decline_own_request(self):
		request = make_request(status="Awaiting Sign-off", logged_by=COMPLIANCE)
		frappe.set_user(COMPLIANCE)
		self.assertRaises(frappe.PermissionError, decline, request.name, "No")

	def test_cannot_decline_after_erasure(self):
		request = self.erased()
		frappe.set_user(COMPLIANCE)
		self.assertRaises(frappe.ValidationError, decline, request.name, "Too late")

	# -- close -----------------------------------------------------------------------------

	def test_close_wipes_identifying_details(self):
		r = self.erased(
			requester_names="Marisol Vega",
			original_message="Please erase me. Marisol",
			contract_references="SO-1001",
			identifiers=[{"kind": "Email", "value": "marisol@x.net"}],
			matches=[
				{
					"reference_doctype": "CRM Lead",
					"reference_name": make_person("m@x.net", "+19165550100")[0].name,
				}
			],
			checklist=[{"description": "Delete the copy at Mailchimp", "done": 1}],
		)
		frappe.set_user(COMPLIANCE)
		close(r.name, today(), "Completed")

		d = frappe.get_doc(REQUEST, r.name)
		self.assertFalse(d.requester_names or d.original_message or d.identifiers or d.matches)
		self.assertFalse(d.contract_references)
		self.assertEqual(d.request_type, "Erasure")
		self.assertTrue(d.received_on and d.channel and d.answered_on)
		self.assertEqual((d.status, d.outcome), ("Closed", "Completed"))
		self.assertEqual(str(d.delete_after), str(add_months(getdate(today()), 24)))
		# The checklist row stays, its text does not.
		self.assertEqual(
			[(row.description, row.done) for row in d.checklist], [(placeholder_content(r.name), 1)]
		)
		self.assertFalse(frappe.db.exists("Version", {"ref_doctype": REQUEST, "docname": r.name}))

	def test_close_erases_emails_attached_to_the_request(self):
		r = self.erased(
			requester_names="Marisol Vega", identifiers=[{"kind": "Email", "value": "marisol@x.net"}]
		)
		email = make_communication(
			reference=(REQUEST, r.name),
			sender="Marisol Vega <Marisol@X.net>",
			recipients="crm@example.com",
			subject="Please erase me",
			content="I am Marisol Vega",
		)
		other = make_communication(sender="bob@x.net", subject="Unrelated", content="Unrelated")
		frappe.set_user(COMPLIANCE)
		close(r.name, today(), "Completed")

		email.reload()
		self.assertEqual((email.subject, email.content), (placeholder_content(r.name),) * 2)
		self.assertNotIn("marisol", email.sender.lower())
		self.assertTrue(frappe.db.exists("Communication", email.name))
		other.reload()
		self.assertEqual(other.subject, "Unrelated")

	def test_close_declined_request_with_denied_outcome(self):
		r = make_request(status="Declined", denial_reason="Identity not verifiable", logged_by=LOGGER)
		frappe.set_user(COMPLIANCE)
		close(r.name, today(), "Denied")
		self.assertEqual(frappe.db.get_value(REQUEST, r.name, "denial_reason"), "Identity not verifiable")
		self.assertEqual(self.status_of(r), "Closed")

	def test_close_declined_request_needs_denied_outcome(self):
		r = make_request(status="Declined", denial_reason="Identity not verifiable", logged_by=LOGGER)
		frappe.set_user(COMPLIANCE)
		for outcome in ("Completed", "Partly completed"):
			self.assertRaises(frappe.ValidationError, close, r.name, today(), outcome)
		self.assertEqual(self.status_of(r), "Declined")

	def test_close_declined_request_new_reason_replaces_decline_reason(self):
		r = make_request(status="Declined", denial_reason="Identity not verifiable", logged_by=LOGGER)
		frappe.set_user(COMPLIANCE)
		close(r.name, today(), "Denied", "Legal exemption")
		self.assertEqual(frappe.db.get_value(REQUEST, r.name, "denial_reason"), "Legal exemption")

	def test_close_wipes_comments_on_the_request(self):
		r = self.erased(requester_names="Marisol Vega")
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": REQUEST,
				"reference_name": r.name,
				"content": "Spoke to Marisol Vega by phone",
			}
		).insert(ignore_permissions=True)
		elsewhere = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "User",
				"reference_name": LOGGER,
				"content": "Unrelated note",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(COMPLIANCE)
		close(r.name, today(), "Completed")
		self.assertEqual(frappe.db.get_value("Comment", comment.name, "content"), placeholder_content(r.name))
		self.assertEqual(frappe.db.get_value("Comment", elsewhere.name, "content"), "Unrelated note")

	def test_close_denied_needs_reason(self):
		r = self.erased()
		frappe.set_user(COMPLIANCE)
		self.assertRaises(frappe.ValidationError, close, r.name, today(), "Denied")
		close(r.name, today(), "Denied", "Legal hold")
		self.assertEqual(frappe.db.get_value(REQUEST, r.name, "denial_reason"), "Legal hold")

	def test_close_blocked_by_open_checklist_and_changes_nothing(self):
		r = self.erased(
			requester_names="Marisol Vega", checklist=[{"description": "Delete at provider", "done": 0}]
		)
		frappe.set_user(COMPLIANCE)
		self.assertRaises(frappe.ValidationError, close, r.name, today(), "Completed")
		r.reload()
		self.assertEqual((r.status, r.requester_names), ("Erased", "Marisol Vega"))

	def test_close_needs_erased_or_declined_status(self):
		for status in ("Logged", "Awaiting Sign-off", "Erasing", "Closed"):
			r = make_request(status=status, logged_by=LOGGER)
			frappe.set_user(COMPLIANCE)
			self.assertRaises(frappe.ValidationError, close, r.name, today(), "Completed")
			frappe.set_user("Administrator")

	def test_close_is_compliance_only(self):
		r = self.erased()
		for user in (LOGGER, MANAGER):
			frappe.set_user(user)
			self.assertRaises(frappe.PermissionError, close, r.name, today(), "Completed")

	def test_close_rejects_unknown_outcome(self):
		r = self.erased()
		frappe.set_user(COMPLIANCE)
		self.assertRaises(frappe.ValidationError, close, r.name, today(), "Whatever")
		self.assertRaises(frappe.ValidationError, close, r.name, "", "Completed")

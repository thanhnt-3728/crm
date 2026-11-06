# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import hashlib
from unittest.mock import patch

import frappe

from crm.api import erasure as api
from crm.erasure import jobs
from crm.erasure.approval import ErasurePreviewStale
from crm.erasure.erasure_test_fixture_base import OPEN_STATUS
from crm.erasure.erasure_test_fixture_execution import (
	REQUEST,
	commits_recorded,
	db_values,
	pending_marisol_request,
)
from crm.erasure.erasure_test_fixtures import HER_EMAILS, raw_insert
from crm.erasure.match_rows import VIA_EXCLUDED, format_key
from crm.erasure.test_executor import ExecutorCase
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import MANAGER, PO, PO_REP, REP, as_user


class ApprovalCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.enqueue = patch.object(frappe, "enqueue").start()
		self.addCleanup(patch.stopall)

	def preview(self, request, user=PO):
		with as_user(user):
			return api.get_approval_preview(request.name)

	def approve(self, request, user=PO, confirm=None, excluded=(), preview_hash=None):
		preview_hash = preview_hash or self.preview(request)["preview_hash"]
		with as_user(user), commits_recorded():
			return api.approve(request.name, request.name if confirm is None else confirm, list(excluded), preview_hash)

	def status(self, request):
		return frappe.db.get_value(REQUEST, request.name, "status")


class TestApproval(ApprovalCase):
	def test_preview_shape_and_hash(self):
		request = pending_marisol_request(self.fx)
		new = raw_insert({"doctype": "Communication", "communication_type": "Communication", "sender": REP, "recipients": HER_EMAILS[0]})
		payload = self.preview(request)
		for key in ("name", "status", "hold_reason", "ack_due", "response_due", "groups", "hidden", "identifiers_not_on_subject"):
			self.assertIn(key, payload)
		rows = {row["key"]: row for group in payload["groups"] for row in group["rows"]}
		self.assertTrue(all({"key", "excluded", "new_since_logging"} <= set(row) for row in rows.values()))
		self.assertGreater(sum(group["unreadable"] for group in payload["groups"]), 0)
		stored = {format_key(m.ref_doctype, m.ref_name) for m in request.matches}
		expected = hashlib.sha256("\n".join(sorted(stored | {format_key("Communication", new.name)})).encode()).hexdigest()
		self.assertEqual(payload["preview_hash"], expected)  # every row, readable or not
		self.assertEqual(len(request.matches), len(frappe.get_doc(REQUEST, request.name).matches))  # read-only

	def test_two_person_rule_and_typed_confirmation(self):
		request = pending_marisol_request(self.fx)
		for user in (REP, MANAGER):
			with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
				self.approve(request, user=user, preview_hash="x")
		for typed in (request.name.lower(), request.name + "x", "", request.name.replace("-", "")):
			with self.subTest(typed=typed), self.assertRaises(frappe.ValidationError):
				self.approve(request, confirm=typed)
		self.assertEqual(self.status(request), "Pending Approval")
		self.approve(request, confirm=f"  {request.name} ")  # control: surrounding spaces are fine
		state = db_values(REQUEST, request.name, ("status", "approver", "approved_on"))
		self.assertEqual((state["status"], state["approver"]), ("Approved", PO))
		self.assertTrue(state["approved_on"])

	def test_self_approval_rejected(self):
		request = pending_marisol_request(self.fx)
		frappe.db.set_value(REQUEST, request.name, {"requested_by": PO_REP, "owner": PO_REP}, update_modified=False)
		with self.assertRaises(frappe.PermissionError):
			self.approve(request, user=PO_REP, preview_hash="x")

	def test_hold_on_approve(self):
		request = pending_marisol_request(self.fx)
		frappe.db.set_value("CRM Deal", self.fx.deal_open, "status", OPEN_STATUS, update_modified=False)
		lead = db_values("CRM Lead", self.fx.lead, ("first_name", "email"))
		with self.assertRaises(frappe.ValidationError):
			self.approve(request)
		self.assertEqual(self.status(request), "On Hold")
		self.assertIn(self.fx.deal_open, frappe.db.get_value(REQUEST, request.name, "hold_reason"))
		self.assertEqual(db_values("CRM Lead", self.fx.lead, lead), lead)
		self.enqueue.assert_not_called()

	def test_stale_preview(self):
		request = pending_marisol_request(self.fx)
		stale = self.preview(request)["preview_hash"]
		raw_insert({"doctype": "Communication", "communication_type": "Communication", "sender": REP, "recipients": HER_EMAILS[1]})
		with self.assertRaises(ErasurePreviewStale) as raised:
			self.approve(request, preview_hash=stale)
		self.assertIn("changed", str(raised.exception).lower())
		self.assertIn("reload", str(raised.exception).lower())
		self.assertEqual(self.status(request), "Pending Approval")
		self.enqueue.assert_not_called()

	def test_approve_persists_exclusions_and_enqueues(self):
		request = pending_marisol_request(self.fx)
		key = format_key("FCRM Note", self.name("note_on_deal"))
		self.assertEqual(self.approve(request, excluded=[key])["status"], "Approved")
		request.reload()
		excluded = {format_key(m.ref_doctype, m.ref_name) for m in request.matches if m.excluded}
		self.assertEqual(excluded, {key})
		self.enqueue.assert_called_once()
		args, kwargs = self.enqueue.call_args
		self.assertEqual(args[0], "crm.erasure.jobs.execute_request")
		expect = {"queue": "long", "timeout": 1500, "job_id": f"crm-erasure::{request.name}", "deduplicate": True, "enqueue_after_commit": True, "name": request.name}
		self.assertEqual({k: kwargs.get(k) for k in expect}, expect)

	def test_second_approve_throws(self):
		request = pending_marisol_request(self.fx)
		preview_hash = self.preview(request)["preview_hash"]
		self.approve(request, preview_hash=preview_hash)
		with self.assertRaises(frappe.ValidationError):
			self.approve(request, preview_hash=preview_hash)
		self.enqueue.assert_called_once()

	def test_unreadable_exclusion_survives_approval(self):
		request = pending_marisol_request(self.fx, excluded=("comm_sms",))
		sms = db_values("Communication", self.name("comm_sms"), ("content", "phone_no"))
		self.approve(request, excluded=[])  # the PO cannot read it, so cannot see it to keep it excluded
		request.reload()
		self.assertTrue(next(m for m in request.matches if m.ref_name == self.name("comm_sms")).excluded)
		with commits_recorded():
			jobs.execute_request(request.name)
		self.assertEqual(self.status(request), "Executed")
		self.assertEqual(db_values("Communication", self.name("comm_sms"), sms), sms)

	def test_exclusion_at_approve_drops_what_is_reached_only_through_it(self):
		request = pending_marisol_request(self.fx)
		call = format_key("CRM Call Log", self.name("call_on_lead"))
		only_via_call = {self.name("note_by_call"), self.name("task_by_call")}
		before = {label: db_values(dt, self.name(label), ("title",)) for dt, label in (("FCRM Note", "note_by_call"), ("CRM Task", "task_by_call"))}
		self.approve(request, excluded=[call])
		request.reload()
		rows = {m.ref_name: m for m in request.matches}
		for name in only_via_call:
			self.assertEqual((rows[name].excluded, rows[name].reason), (1, VIA_EXCLUDED))
		with commits_recorded():
			jobs.execute_request(request.name)
		for (doctype, label), values in zip((("FCRM Note", "note_by_call"), ("CRM Task", "task_by_call")), before.values()):
			self.assertEqual(db_values(doctype, self.name(label), values), values)

	def test_excluded_keys_must_be_readable_matches(self):
		request = pending_marisol_request(self.fx)
		for key in (format_key("Communication", self.name("comm_sms")), "Note::nope", "garbage"):
			with self.subTest(key=key), self.assertRaises(frappe.ValidationError):
				self.approve(request, excluded=[key])
		self.assertEqual(self.status(request), "Pending Approval")


class TestDecisions(ApprovalCase):
	def test_reject(self):
		request = pending_marisol_request(self.fx)
		with as_user(PO), self.assertRaises(frappe.ValidationError):
			api.reject(request.name, "   ")
		with as_user(REP), self.assertRaises(frappe.PermissionError):
			api.reject(request.name, "Not a customer")
		with as_user(PO):
			self.assertEqual(api.reject(request.name, "Identity not verified")["status"], "Rejected")
		self.assertEqual(frappe.db.get_value(REQUEST, request.name, "rejection_reason"), "Identity not verified")

	def test_retry_execution(self):
		request = pending_marisol_request(self.fx)
		with as_user(PO), self.assertRaises(frappe.ValidationError):
			api.retry_execution(request.name)  # not Approved
		self.approve(request)
		self.enqueue.reset_mock()
		with as_user(REP), self.assertRaises(frappe.PermissionError):
			api.retry_execution(request.name)
		with as_user(PO):
			api.retry_execution(request.name)
		self.assertEqual(self.enqueue.call_args.kwargs["job_id"], f"crm-erasure::{request.name}")

	def test_endpoints_are_post_only_and_typed(self):
		for method in ("get_approval_preview", "approve", "reject", "close", "retry_execution"):
			with self.subTest(method=method):
				fn = getattr(api, method)
				self.assertIn(fn, frappe.whitelisted)
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"])
				self.assertTrue(set(fn.__code__.co_varnames[: fn.__code__.co_argcount]) <= set(fn.__annotations__))

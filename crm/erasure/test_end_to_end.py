# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Phase 05 gate: one person erased end to end, with versioning on, as in production (B1, B2)

rep logs -> submit -> On Hold (her open deal) -> deals closed by their owners -> Pending Approval
-> dashboard snapshot -> rep cannot approve -> PO approves with the typed number -> job -> checks
"""

import json
import os
import time
from unittest.mock import patch

import frappe
from frappe.utils import today

from crm.api import erasure as api
from crm.erasure import jobs, verify
from crm.erasure.erasure_test_fixture_base import WON_STATUS
from crm.erasure.erasure_test_fixture_end_to_end import (
	LOST_STATUS,
	add_tracked_edits,
	cleanup_end_to_end,
	dashboard_snapshot,
	table_digest,
)
from crm.erasure.erasure_test_fixture_execution import (
	REQUEST,
	commits_recorded,
	db_values,
	full_name_hits,
	her_identifier_strings,
	remove_disk_file,
	run_executor,
	write_disk_file,
)
from crm.erasure.erasure_test_fixtures import COLLEAGUE_EMAIL, HER_EMAILS, HER_IMAGE_URL, HER_PHONES
from crm.erasure.identifiers import Identifiers
from crm.erasure.retention import retention_rows
from crm.erasure.test_executor import DEAL_KEPT, LEAD_KEPT, ExecutorCase
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import PO, REP, REP2, as_user, set_deal_status

DISK_FILES = ("file_on_lead", "file_on_email")


class TestEndToEnd(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.request_name = None
		self.paths = {label: write_disk_file(f"/private/files/{label}.txt") for label in DISK_FILES}
		self.paths["shared_image"] = write_disk_file(HER_IMAGE_URL)

	def tearDown(self):
		for path in self.paths.values():
			remove_disk_file(path)
		super().tearDown()
		cleanup_end_to_end(self.request_name)

	def test_erasure_end_to_end(self):
		started = time.monotonic()
		with (
			patch.object(frappe, "in_test", False),
			patch.object(frappe, "enqueue") as enqueue,
			commits_recorded(),
		):
			self.versions = add_tracked_edits(self.fx)
			self.assertTrue(self.versions, "versioning is on: the rep's edits wrote Version rows")
			name = self.log_and_hold()
			before = self.snapshot()
			self.assertGreater(len(before), 40, "(a) dashboard endpoints were not discovered")
			self.approve(name, enqueue)
			self.assert_delete_blocked()
			kept = self.kept_values()
			jobs.execute_request(name)
			self.assert_executed(name, before, kept)
			self.assert_second_run_changes_nothing(name)
			self.assert_close_and_delete(name)
		self.assertLess(time.monotonic() - started, 30)

	# flow

	def log_and_hold(self) -> str:
		with as_user(REP):
			payload = api.log_request(
				"CRM Lead", self.fx.lead, "Marisol Reyes", today(), list(HER_EMAILS), list(HER_PHONES)
			)
			self.request_name = name = payload["name"]
			held = api.submit_for_approval(name)
		self.assertEqual(held["status"], "On Hold")
		self.assertIn(self.fx.deal_open, held["hold_reason"])
		with as_user(REP):  # the deal owner loses Deal B
			set_deal_status(self.fx.deal_open, LOST_STATUS)
		self.assertEqual(self.status(name), "On Hold")  # the colleague's deal she is a contact on is open
		with as_user(REP2):
			set_deal_status(self.fx.colleague_deal, WON_STATUS)
		self.assertEqual(self.status(name), "Pending Approval")
		return name

	def approve(self, name: str, enqueue):
		with as_user(REP), self.assertRaises(frappe.PermissionError):
			api.approve(name, name, [], "")
		with as_user(PO):
			preview = api.get_approval_preview(name)
			with self.assertRaises(frappe.ValidationError):
				api.approve(name, f"{name}-typo", [], preview["preview_hash"])
			self.assertEqual(self.status(name), "Pending Approval")
			self.assertEqual(api.approve(name, name, [], preview["preview_hash"])["status"], "Approved")
		self.assertEqual(enqueue.call_args.args[0], jobs.JOB_METHOD)

	def assert_delete_blocked(self):
		frappe.db.savepoint("e2e_delete")
		with self.assertRaisesRegex(frappe.ValidationError, "erasure request"):
			frappe.delete_doc("CRM Lead", self.fx.lead, ignore_permissions=True)
		frappe.db.rollback(save_point="e2e_delete")

	# checks

	def assert_executed(self, name: str, before: dict, kept: dict):
		state = db_values(REQUEST, name, ("status", "last_error", "outcome"))
		self.assertEqual((state["status"], state["last_error"]), ("Executed", None), "the job did not finish")
		after = self.snapshot()
		moved = sorted(key for key in before if before[key] != after[key])
		self.assertEqual(moved, [], "(a) dashboard numbers moved")
		request = frappe.get_doc(REQUEST, name)
		ids = Identifiers.from_rows(request.identifiers)
		self.assertEqual(verify.full_scan(ids), [], "(b) her identifiers are still stored")
		self.assertEqual(full_name_hits(self.fx, "marisol reyes"), [], "(b) her full name is still stored")
		self.assertEqual(self.kept_values(), kept, "(c) kept fields changed")
		cc = db_values("Communication", self.fx.names["comm_cc_on_colleague_deal"], ("cc",))["cc"]
		self.assertIn(COLLEAGUE_EMAIL, cc, "(c) the colleague's address left the cc")
		outcome = json.loads(state["outcome"])
		self.assertTrue(outcome["changed"], "(d) the outcome has no counts")
		self.assertEqual(outcome["files_deleted"], 3, "(d)/(f) her File rows")
		for text in her_identifier_strings():
			self.assertNotIn(text.lower(), state["outcome"].lower(), "(d) the outcome names her")
		for label in DISK_FILES:
			self.assertFalse(os.path.exists(self.paths[label]), f"(f) {label} is still on disk")
		self.assertTrue(os.path.exists(self.paths["shared_image"]), "(f) a colleague's file was deleted")
		self.assertFalse(
			frappe.db.exists("Version", {"name": ["in", self.versions]}), "(b) Version of her edits"
		)

	def assert_second_run_changes_nothing(self, name: str):
		state = db_values(REQUEST, name, ("status", "outcome", "last_error"))
		tables = verify.registry_tables()
		digest = table_digest(tables)
		jobs.execute_request(name)  # not Approved any more: refuses
		self.assertEqual(dict(run_executor(frappe.get_doc(REQUEST, name)).counts), {}, "(e) second run")
		self.assertEqual(db_values(REQUEST, name, state), state, "(e) second job run")
		self.assertEqual(table_digest(tables), digest, "(e) second run changed rows")

	def assert_close_and_delete(self, name: str):
		with as_user(PO):
			self.assertEqual(api.close(name)["status"], "Closed")
		closed = frappe.get_doc(REQUEST, name)
		self.assertEqual([r.value for r in closed.identifiers], [r["value"] for r in retention_rows(closed)])
		self.assertNotIn("marisol.reyes", frappe.as_json(closed.as_dict()).lower(), "(g) retention")
		frappe.delete_doc("CRM Lead", self.fx.lead, ignore_permissions=True, force=True)
		self.assertFalse(frappe.db.exists("CRM Lead", self.fx.lead), "(g) delete after Close")

	def snapshot(self) -> dict:
		return dashboard_snapshot((None, REP))

	def kept_values(self) -> dict:
		deals = {
			deal: db_values("CRM Deal", deal, DEAL_KEPT) for deal in (self.fx.deal_won, self.fx.deal_open)
		}
		return {"lead": db_values("CRM Lead", self.fx.lead, LEAD_KEPT), **deals}

	def status(self, name: str) -> str:
		return frappe.db.get_value(REQUEST, name, "status")

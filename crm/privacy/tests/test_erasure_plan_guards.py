# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the approval covers, a bounded WhatsApp scan, whole-word address names, silent renames (review L1-L5)."""

import contextlib
import json
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from crm.api.erasure_review import set_contract_references
from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.erasure.scrub_names import holds_her_name
from crm.privacy.erasure.value_matcher import Identifiers
from crm.privacy.tests.erasure_run_case import ExecutorCase, snapshot
from crm.privacy.tests.make_test_user import as_user

PLAN_CHANGED = "Plan changed since approval; review and approve again"


class GuardCase(ExecutorCase):
	def assertPlanChanged(self):
		before = snapshot()
		self.run_job()
		stored = self.stored("status", "erasure_job_status", "erasure_error")
		self.assertEqual(
			(stored.status, stored.erasure_job_status, stored.erasure_error),
			("Awaiting sign-off", "Failed", PLAN_CHANGED),
		)
		self.assertEqual(snapshot(), before)


class TestWhatTheHashCovers(GuardCase):
	def test_retention_months_changed_after_approval_fail_the_job(self):  # L1
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 36)
		as_user(self.compliance, set_contract_references, self.request, ["CT-1"])
		self.approve()
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 0)
		self.assertPlanChanged()
		self.assertEqual(frappe.db.count("CRM Retained Contract"), 0)

	def test_the_personal_fields_list_edited_after_approval_fails_the_job(self):  # L2
		self.approve()
		settings = frappe.get_doc("CRM Privacy Settings")
		settings.append("personal_fields", {"document_type": "CRM Lead", "fieldname": "website"})
		settings.save(ignore_permissions=True)
		self.assertPlanChanged()

	def test_the_plan_carries_the_months_and_the_list(self):
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 18)
		plan = build_plan(frappe.get_doc("CRM Erasure Request", self.request))
		self.assertEqual(plan.retention_months, 18)
		self.assertIn("email", plan.personal_fields["CRM Lead"])


class TestBoundedWhatsAppScan(GuardCase):
	def test_messages_from_other_numbers_are_not_loaded_to_be_compared(self):  # L3
		account = frappe.db.get_value("WA Message", self.activity.misc.wa_message, "whatsapp_account")
		profile = frappe.get_doc({"doctype": "WA Profile", "whatsapp_account": account, "phone_number": "+19995550100",
			"profile_name": "Other"}).insert(ignore_permissions=True)  # fmt: skip
		others = [f"+1999555{n:04d}" for n in range(12)]
		for number in others:
			frappe.get_doc({"doctype": "WA Message", "direction": "Incoming", "whatsapp_account": account,
				"to": profile.name, "from": number, "message": "hello"}).insert(ignore_permissions=True)  # fmt: skip
		compared = []
		from crm.privacy.erasure import plan_misc

		real = plan_misc.same_phone

		def spy(stored, phones):
			compared.append(stored)
			return real(stored, phones)

		with patch.object(plan_misc, "same_phone", spy):
			build_plan(frappe.get_doc("CRM Erasure Request", self.request))
		self.assertFalse([n for n in others if n in compared], "unrelated numbers were compared in Python")


class TestWholeWordAddressNames(UnitTestCase):
	def plan(self, **values):
		return ErasurePlan("PDR-0001", Identifiers.of([("email", "m.vega@example.com")]), her_values=values)

	def test_a_name_inside_a_longer_word_is_not_hers(self):  # L4
		plan = self.plan(full_name=["Ana"])
		self.assertFalse(holds_her_name("Banana St-Billing", plan))
		self.assertFalse(holds_her_name("Anaheim Office-Office", plan))
		self.assertTrue(holds_her_name("Ana-Billing", plan))
		self.assertTrue(holds_her_name("Office of ana", plan))

	def test_a_full_name_or_an_identifier_as_whole_words(self):
		plan = self.plan(full_name=["Marisol Vega"], lead_name=["Marisol Vega"])
		self.assertTrue(holds_her_name("Marisol Vega-Billing", plan))
		self.assertTrue(holds_her_name("billing for m.vega@example.com", plan))
		self.assertFalse(holds_her_name("Marisol Vegas-Billing", plan))
		self.assertFalse(holds_her_name("Sierra Office-Office", plan))


class TestSilentRename(GuardCase):
	def realtime_during_the_job(self) -> list[str]:
		emitted = []
		self.approve()
		frappe.realtime.clear_realtime_log()
		with (
			patch(
				"frappe.realtime.emit_via_redis",
				lambda event, message, room: emitted.append(json.dumps(message, default=str)),
			),
			patch("frappe.publish_realtime", wraps=frappe.publish_realtime) as publish,
		):
			self.run_job()
		self.assertEqual(self.stored("status").status, "Erased")
		sent = [json.dumps(c.kwargs, default=str) for c in publish.call_args_list]
		return sent + emitted + [json.dumps(getattr(frappe.local, "_realtime_log", []), default=str)]

	def test_no_realtime_message_names_the_old_docname(self):  # L5
		every = self.realtime_during_the_job()
		self.assertFalse([m for m in every if self.p.contact in m or self.p.address in m], every)

	def test_the_check_can_see_a_rename_that_is_not_muted(self):
		with patch("crm.privacy.erasure.rename_support.muted_realtime", contextlib.nullcontext):
			every = self.realtime_during_the_job()
		self.assertTrue([m for m in every if self.p.contact in m], "the detector is blind")

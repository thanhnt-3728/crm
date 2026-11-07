from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from crm.privacy.api import close_request, decline_request
from crm.privacy.install import seed_outcome_template
from crm.privacy.lifecycle import purge_expired
from crm.privacy.tests.factories import make_communication, make_compliance_user, make_request

DOCTYPE = "CRM Erasure Request"


class TestLifecycle(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _status(self, name, status, **values):
		frappe.db.set_value(DOCTYPE, name, {"status": status, **values})

	def test_decline_requires_reason(self):
		officer = make_compliance_user()
		r = make_request()
		frappe.set_user(officer)
		with self.assertRaises(frappe.ValidationError):
			decline_request(r.name, "  ")
		self.assertEqual(decline_request(r.name, "Identity not verifiable")["status"], "Declined")
		self.assertEqual(frappe.db.get_value(DOCTYPE, r.name, "decline_reason"), "Identity not verifiable")

	def test_decline_needs_compliance_and_open_status(self):
		officer = make_compliance_user()
		r = make_request()
		with self.assertRaises(frappe.PermissionError):
			frappe.set_user("Guest")
			decline_request(r.name, "No")
		frappe.set_user(officer)
		self._status(r.name, "Erased")
		with self.assertRaises(frappe.ValidationError):
			decline_request(r.name, "Too late")

	def test_close_blocked_by_open_checklist(self):
		officer = make_compliance_user()
		r = make_request(checklist=[{"description": "Delete recordings at provider (Twilio)"}])
		self._status(r.name, "Erased")
		frappe.set_user(officer)
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, today(), "Completed")

	def test_close_wipes_and_keeps_log_fields(self):
		officer = make_compliance_user()
		r = make_request(
			requester_name="Marisol Vega",
			original_message="Delete me",
			arrived_via="Email",
			date_received="2026-10-26",
			identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"}],
			checklist=[{"description": "Ask Marisol Vega's lawyer"}],
		)
		c = make_communication(
			sender="marisol@sierrafoothills.example", reference=(DOCTYPE, r.name), recipients="a@b.example"
		)
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": DOCTYPE,
				"reference_name": r.name,
				"content": "Spoke to Marisol",
			}
		).insert(ignore_permissions=True)
		self._status(r.name, "Erased")
		frappe.db.set_value(DOCTYPE, r.name, "contract_references", "MSA-1")
		frappe.db.set_value("CRM Erasure Checklist Item", {"parent": r.name}, "done", 1)
		frappe.set_user(officer)
		answered = str(add_days(today(), -1))  # never in the future, whatever the date the suite runs
		close_request(r.name, answered, "Completed")
		d = frappe.get_doc(DOCTYPE, r.name)
		self.assertEqual((d.requester_name, d.original_message, d.identifiers, d.matches), ("", "", [], []))
		self.assertFalse(d.contract_references)
		self.assertEqual(
			(str(d.date_received), d.request_type, d.arrived_via, str(d.date_answered), d.outcome, d.status),
			("2026-10-26", "Erasure", "Email", answered, "Completed", "Closed"),
		)
		self.assertEqual(d.checklist[0].description, f"Content erased {r.name}")
		self.assertEqual(frappe.db.get_value("Communication", c, "content"), f"Content erased {r.name}")
		self.assertEqual(frappe.db.get_value("Communication", c, "sender"), f"Erased person {r.name}")
		self.assertEqual(
			frappe.db.get_value(
				"Comment", {"reference_doctype": DOCTYPE, "reference_name": r.name}, "content"
			),
			f"Content erased {r.name}",
		)

	def test_denied_needs_reason(self):
		officer = make_compliance_user()
		r = make_request()
		self._status(r.name, "Erased")
		frappe.set_user(officer)
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, today(), "Denied")
		close_request(r.name, today(), "Denied", "Legal hold")
		self.assertEqual(frappe.db.get_value(DOCTYPE, r.name, "denial_reason"), "Legal hold")

	def test_declined_closes_only_as_denied_with_default_reason(self):
		officer = make_compliance_user()
		r = make_request()
		frappe.set_user(officer)
		decline_request(r.name, "Identity not verifiable")
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, today(), "Completed")
		close_request(r.name, today(), "Denied")
		self.assertEqual(
			frappe.db.get_value(DOCTYPE, r.name, ["status", "outcome", "denial_reason"]),
			("Closed", "Denied", "Identity not verifiable"),
		)
		# The free-text decline reason may name the requester, so it does not outlive the close.
		self.assertFalse(frappe.db.get_value(DOCTYPE, r.name, "decline_reason"))

	def test_blank_date_answered_is_refused(self):
		officer = make_compliance_user()
		r = make_request()
		self._status(r.name, "Erased")
		frappe.set_user(officer)
		for blank in ("", "  ", None):
			with self.assertRaises(frappe.ValidationError):
				close_request(r.name, blank, "Completed")
		self.assertEqual(frappe.db.get_value(DOCTYPE, r.name, "status"), "Erased")

	def test_purge_skips_a_failing_record_and_goes_on(self):
		bad = make_request(date_received="2024-01-02")
		good = make_request(date_received="2024-01-03")
		for r in (bad, good):
			frappe.db.set_value(DOCTYPE, r.name, {"status": "Closed", "date_answered": "2024-01-10"})
		real = frappe.delete_doc

		def flaky(doctype, name, *args, **kwargs):
			if name == bad.name:
				raise RuntimeError("boom")
			return real(doctype, name, *args, **kwargs)

		with patch("frappe.delete_doc", side_effect=flaky), patch("frappe.log_error") as log_error:
			purge_expired(getdate("2026-11-07"))
		self.assertTrue(frappe.db.exists(DOCTYPE, bad.name))
		self.assertFalse(frappe.db.exists(DOCTYPE, good.name))
		log_error.assert_called_once()
		self.assertEqual(log_error.call_args.kwargs["title"], f"Erasure purge failed for {bad.name}")

	def test_close_date_checks_and_role(self):
		officer = make_compliance_user()
		r = make_request(date_received="2026-10-26")
		self._status(r.name, "Erased")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			close_request(r.name, today(), "Completed")
		frappe.set_user(officer)
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, "2026-10-25", "Completed")
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, str(add_days(today(), 1)), "Completed")
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, today(), "Bogus")
		self.assertEqual(frappe.db.get_value(DOCTYPE, r.name, "status"), "Erased")

	def test_purge(self):
		r = make_request(date_received="2024-01-02")
		frappe.db.set_value(DOCTYPE, r.name, {"status": "Closed", "date_answered": "2024-01-10"})
		make_communication(sender="someone@example.com", reference=(DOCTYPE, r.name))
		recent = make_request(date_received="2026-01-02")
		frappe.db.set_value(DOCTYPE, recent.name, {"status": "Closed", "date_answered": "2026-01-10"})
		open_old = make_request(date_received="2024-01-02")
		rc = frappe.get_doc(
			{"doctype": "CRM Retained Contract", "person_name": "X", "delete_after": "2026-11-07"}
		).insert()
		keep = frappe.get_doc(
			{"doctype": "CRM Retained Contract", "person_name": "Y", "delete_after": "2026-11-08"}
		).insert()
		purge_expired(getdate("2026-11-07"))
		self.assertFalse(frappe.db.exists(DOCTYPE, r.name))
		self.assertTrue(frappe.db.exists(DOCTYPE, recent.name))
		self.assertTrue(frappe.db.exists(DOCTYPE, open_old.name))
		self.assertFalse(frappe.db.exists("CRM Retained Contract", rc.name))
		self.assertTrue(frappe.db.exists("CRM Retained Contract", keep.name))
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": r.name}))

	def test_outcome_template_seeded_once(self):
		seed_outcome_template()
		self.assertEqual(
			frappe.db.get_value("Email Template", "Erasure outcome", ["enabled", "reference_doctype"]),
			(1, DOCTYPE),
		)
		frappe.db.set_value("Email Template", "Erasure outcome", "subject", "Edited")
		seed_outcome_template()
		self.assertEqual(frappe.db.get_value("Email Template", "Erasure outcome", "subject"), "Edited")
